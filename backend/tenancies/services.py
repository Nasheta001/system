from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from billing.models import Charge
from billing.services import account_summary, generate_charges_for_tenancy
from properties.models import Unit

from .models import Tenancy, Tenant

ZERO = Decimal("0")


def _notify(tenant, message):
    from communications.services import notify_tenant

    transaction.on_commit(lambda: notify_tenant(tenant, "tenancy_change", {"message": message},
                                                link="/tenant/dashboard"))


@transaction.atomic
def move_in(tenant, unit_id, start_date, *, user=None, monthly_rent=None, service_charge=None, deposit_amount=None,
            rent_due_day=None, grace_days=None, expected_end_date=None, charge_deposit=True, reservation=None,
            reminder_schedule=None, move_in_inspection_notes="", transferred_from=None, notify=True):
    """Create an active tenancy. Locks the unit row so two staff members cannot
    let the same unit at the same time."""
    from accounts.models import CompanySettings
    from leasing.models import Reservation

    unit = Unit.objects.select_for_update(of=("self",)).select_related("property", "building").get(pk=unit_id)
    if unit.is_archived or unit.property.status != "active":
        raise ValidationError({"unit": "This unit is archived."})
    if Tenancy.objects.filter(unit=unit, status__in=Tenancy.CURRENT_STATUSES).exists():
        raise ValidationError({"unit": "This unit already has a current tenancy."})
    active_res = Reservation.objects.select_for_update().filter(unit=unit, status=Reservation.Status.ACTIVE).first()
    if active_res and (reservation is None or active_res.pk != reservation.pk):
        raise ValidationError({"unit": "This unit is reserved for another applicant. Cancel that reservation first."})
    if unit.status in (Unit.Status.MAINTENANCE, Unit.Status.UNAVAILABLE):
        raise ValidationError({"unit": f"This unit is marked '{unit.get_status_display()}'. Make it available first."})

    tenancy = Tenancy.objects.create(
        tenant=tenant, unit=unit, property=unit.property, reservation=reservation, transferred_from=transferred_from,
        start_date=start_date, expected_end_date=expected_end_date,
        monthly_rent=unit.rent_amount if monthly_rent is None else monthly_rent,
        service_charge=unit.service_charge if service_charge is None else service_charge,
        deposit_amount=unit.deposit_amount if deposit_amount is None else deposit_amount,
        charge_deposit=charge_deposit,
        rent_due_day=rent_due_day or unit.rent_due_day,
        grace_days=CompanySettings.load().default_grace_days if grace_days is None else grace_days,
        reminder_schedule=reminder_schedule, move_in_inspection_notes=move_in_inspection_notes, created_by=user,
    )
    unit.status = Unit.Status.OCCUPIED
    unit.available_from = None
    unit.save(update_fields=["status", "available_from", "updated_at"])
    if tenant.status != Tenant.Status.ACTIVE:
        tenant.status = Tenant.Status.ACTIVE
        tenant.save(update_fields=["status", "updated_at"])
    if reservation:
        reservation.status = Reservation.Status.CONVERTED
        reservation.closed_at = timezone.now()
        reservation.save(update_fields=["status", "closed_at"])
    generate_charges_for_tenancy(tenancy, user=user)
    if notify:
        _notify(tenant, f"Welcome! Your tenancy for unit {unit.label} at {unit.property.name} starts on "
                        f"{start_date:%d %b %Y}.")
    return tenancy


@transaction.atomic
def give_notice(tenancy, notice_date, planned_move_out, user=None):
    tenancy = Tenancy.objects.select_for_update().get(pk=tenancy.pk)
    if tenancy.status != Tenancy.Status.ACTIVE:
        raise ValidationError("Notice can only be recorded on an active tenancy.")
    if planned_move_out < notice_date:
        raise ValidationError({"planned_move_out": "Planned move-out must be after the notice date."})
    tenancy.status = Tenancy.Status.NOTICE
    tenancy.notice_date = notice_date
    tenancy.planned_move_out = planned_move_out
    tenancy.save()
    _notify(tenancy.tenant, f"Your notice to vacate has been recorded. Planned move-out: {planned_move_out:%d %b %Y}.")
    return tenancy


@transaction.atomic
def complete_move_out(tenancy, *, actual_move_out, user=None, inspection_date=None, inspection_notes="",
                      deposit_deductions=ZERO, deduction_notes="", apply_deposit_to_balance=True,
                      unit_status_after=Unit.Status.AVAILABLE, unit_available_from=None, notify=True):
    tenancy = Tenancy.objects.select_for_update(of=("self",)).select_related("unit", "tenant").get(pk=tenancy.pk)
    if tenancy.status not in Tenancy.CURRENT_STATUSES:
        raise ValidationError("This tenancy has already ended.")
    if actual_move_out < tenancy.start_date:
        raise ValidationError({"actual_move_out": "Move-out cannot be before the tenancy start date."})
    deposit_deductions = Decimal(deposit_deductions or 0)
    if deposit_deductions < 0 or deposit_deductions > tenancy.deposit_amount:
        raise ValidationError({"deposit_deductions": "Deductions must be between 0 and the deposit amount."})
    if unit_status_after not in (Unit.Status.AVAILABLE, Unit.Status.MAINTENANCE, Unit.Status.UNAVAILABLE):
        raise ValidationError({"unit_status_after": "Invalid unit status."})

    tenancy.actual_move_out = actual_move_out
    generate_charges_for_tenancy(tenancy, as_of=actual_move_out, user=user)
    summary = account_summary(tenancy, actual_move_out)
    remaining_deposit = tenancy.deposit_amount - deposit_deductions
    applied = ZERO
    if apply_deposit_to_balance and summary.balance > 0 and remaining_deposit > 0:
        applied = min(remaining_deposit, summary.balance)
        Charge.objects.create(
            tenancy=tenancy, property_id=tenancy.property_id, kind=Charge.Kind.CREDIT, amount=applied,
            due_date=actual_move_out, description="Deposit applied to outstanding balance at move-out",
            created_by=user,
        )
    tenancy.status = Tenancy.Status.ENDED
    tenancy.move_out_inspection_date = inspection_date
    tenancy.move_out_inspection_notes = inspection_notes
    tenancy.deposit_deductions = deposit_deductions
    tenancy.deposit_deduction_notes = deduction_notes
    tenancy.deposit_applied_to_balance = applied
    tenancy.deposit_refund_amount = remaining_deposit - applied
    tenancy.deposit_reconciled_at = timezone.now()
    tenancy.unit_available_from = unit_available_from or actual_move_out
    tenancy.save()

    unit = Unit.objects.select_for_update().get(pk=tenancy.unit_id)
    unit.status = unit_status_after
    unit.available_from = tenancy.unit_available_from
    unit.save(update_fields=["status", "available_from", "updated_at"])

    tenant = tenancy.tenant
    ended_all = not tenant.tenancies.filter(status__in=Tenancy.CURRENT_STATUSES).exists()
    if ended_all:
        tenant.status = Tenant.Status.FORMER
        tenant.save(update_fields=["status", "updated_at"])
    if notify:
        _notify(tenant, f"Your move-out from {unit.label} has been completed on {actual_move_out:%d %b %Y}. "
                        "Contact the management office if you need a copy of your final statement.")
    if ended_all:
        # No current tenancy left: close the portal (sessions, open invitations).
        # Payments, ledgers and tenancy records are kept for staff and reporting.
        from accounts.invitations import end_tenant_portal_access

        end_tenant_portal_access(tenant, by=user, reason="Tenancy ended (move-out)")
    return tenancy


@transaction.atomic
def transfer(tenancy, new_unit_id, transfer_date, *, user=None, monthly_rent=None):
    """Move a tenant to another unit: end the old tenancy, start a new one and
    carry the balance across so nothing is lost."""
    old = Tenancy.objects.select_for_update().get(pk=tenancy.pk)
    if old.status not in Tenancy.CURRENT_STATUSES:
        raise ValidationError("Only current tenancies can be transferred.")
    if int(new_unit_id) == old.unit_id:
        raise ValidationError({"unit": "Choose a different unit."})
    old.actual_move_out = transfer_date
    generate_charges_for_tenancy(old, as_of=transfer_date, user=user)
    balance = account_summary(old, transfer_date).balance
    old.status = Tenancy.Status.ENDED
    old.unit_available_from = transfer_date
    old.deposit_refund_amount = ZERO
    old.deposit_reconciled_at = timezone.now()
    old.deposit_deduction_notes = "Deposit carried over to new unit on transfer"
    old.save()
    Unit.objects.filter(pk=old.unit_id).update(status=Unit.Status.AVAILABLE, available_from=transfer_date)

    new = move_in(
        old.tenant, new_unit_id, transfer_date, user=user, monthly_rent=monthly_rent,
        deposit_amount=old.deposit_amount, charge_deposit=False, rent_due_day=old.rent_due_day,
        grace_days=old.grace_days, reminder_schedule=old.reminder_schedule, transferred_from=old, notify=False,
    )
    # The current month was already charged on the old unit: don't bill it twice.
    period = transfer_date.replace(day=1)
    for kind in (Charge.Kind.RENT, Charge.Kind.SERVICE):
        if old.charges.filter(kind=kind, period=period, voided=False).exists():
            new.charges.filter(kind=kind, period=period, voided=False).update(
                voided=True, void_reason="Already charged on previous unit for this month (transfer)")
    if balance != 0:
        label_new, label_old = new.unit.label, old.unit.label
        if balance > 0:
            Charge.objects.create(tenancy=old, property_id=old.property_id, kind=Charge.Kind.CREDIT, amount=balance,
                                  due_date=transfer_date, description=f"Balance transferred to {label_new}",
                                  created_by=user)
            Charge.objects.create(tenancy=new, property_id=new.property_id, kind=Charge.Kind.OTHER, amount=balance,
                                  due_date=transfer_date, description=f"Balance brought forward from {label_old}",
                                  created_by=user)
        else:
            Charge.objects.create(tenancy=old, property_id=old.property_id, kind=Charge.Kind.OTHER, amount=-balance,
                                  due_date=transfer_date, description=f"Credit transferred to {label_new}",
                                  created_by=user)
            Charge.objects.create(tenancy=new, property_id=new.property_id, kind=Charge.Kind.CREDIT, amount=-balance,
                                  due_date=transfer_date, description=f"Credit brought forward from {label_old}",
                                  created_by=user)
    _notify(old.tenant, f"Your tenancy has been transferred to unit {new.unit.label} at {new.property.name} "
                        f"from {transfer_date:%d %b %Y}.")
    return new
