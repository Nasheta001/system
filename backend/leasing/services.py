from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from accounts.models import CompanySettings
from properties.models import Unit
from tenancies.models import Tenancy

from .models import RentalApplication, Reservation


def notify_applicant(application):
    from communications.services import notify_address

    context = {
        "first_name": application.full_name.split(" ")[0],
        "reference": application.reference,
        "status": application.get_status_display(),
        "message": application.applicant_message,
    }
    transaction.on_commit(lambda: notify_address(
        "email", application.email, "application_status", context,
        dedupe=f"app:{application.pk}:{application.status}", related=("RentalApplication", application.pk),
    ))


@transaction.atomic
def set_application_status(application, status, user=None, applicant_message=None, internal_notes=None):
    app = RentalApplication.objects.select_for_update().get(pk=application.pk)
    allowed = {
        RentalApplication.Status.PENDING: {"under_review", "approved", "rejected", "withdrawn"},
        RentalApplication.Status.UNDER_REVIEW: {"approved", "rejected", "withdrawn", "pending"},
        RentalApplication.Status.APPROVED: {"withdrawn", "rejected", "under_review"},
        RentalApplication.Status.REJECTED: {"under_review"},
        RentalApplication.Status.WITHDRAWN: set(),
    }
    if status != app.status and status not in allowed.get(app.status, set()):
        raise ValidationError({"status": f"Cannot change an application from {app.status} to {status}."})
    changed = status != app.status
    app.status = status
    if applicant_message is not None:
        app.applicant_message = applicant_message
    if internal_notes is not None:
        app.internal_notes = internal_notes
    app.reviewed_by = user
    app.reviewed_at = timezone.now()
    app.save()
    if changed and status in ("rejected", "withdrawn"):
        for res in app.reservations.filter(status=Reservation.Status.ACTIVE):
            cancel_reservation(res, user=user, reason=f"Application {status}")
    if changed:
        notify_applicant(app)
    return app


@transaction.atomic
def reserve_unit(unit_id, *, holder_name, holder_phone, holder_email="", application=None, expires_at=None,
                 user=None, notes=""):
    """Reserve an available unit. The unit row is locked and a partial unique
    constraint guarantees at most one active reservation per unit, so two
    concurrent requests cannot both succeed."""
    unit = Unit.objects.select_for_update(of=("self",)).select_related("property").get(pk=unit_id)
    if unit.is_archived or unit.status != Unit.Status.AVAILABLE:
        raise ValidationError({"unit": "This unit is no longer available for reservation."})
    if Tenancy.objects.filter(unit=unit, status__in=Tenancy.CURRENT_STATUSES).exists():
        raise ValidationError({"unit": "This unit has a current tenancy."})
    if Reservation.objects.filter(unit=unit, status=Reservation.Status.ACTIVE).exists():
        raise ValidationError({"unit": "This unit is already reserved."})
    if application is not None:
        if application.status != RentalApplication.Status.APPROVED:
            raise ValidationError({"application": "Only approved applications can reserve a unit."})
        if application.unit_id != unit.pk:
            raise ValidationError({"application": "The application is for a different unit."})
    if expires_at is None:
        expires_at = timezone.now() + timedelta(days=CompanySettings.load().reservation_expiry_days)
    if expires_at <= timezone.now():
        raise ValidationError({"expires_at": "Expiry must be in the future."})
    try:
        with transaction.atomic():
            reservation = Reservation.objects.create(
                unit=unit, property=unit.property, application=application, holder_name=holder_name,
                holder_phone=holder_phone, holder_email=holder_email, expires_at=expires_at,
                release_to_status=unit.status, reserved_by=user, notes=notes,
            )
    except IntegrityError as exc:
        raise ValidationError({"unit": "This unit was just reserved by someone else."}) from exc
    unit.status = Unit.Status.RESERVED
    unit.save(update_fields=["status", "updated_at"])
    return reservation


def _release_unit(reservation):
    unit = Unit.objects.select_for_update().get(pk=reservation.unit_id)
    if unit.status == Unit.Status.RESERVED and not Tenancy.objects.filter(
        unit=unit, status__in=Tenancy.CURRENT_STATUSES
    ).exists():
        unit.status = reservation.release_to_status or Unit.Status.AVAILABLE
        unit.save(update_fields=["status", "updated_at"])


@transaction.atomic
def cancel_reservation(reservation, user=None, reason=""):
    res = Reservation.objects.select_for_update().get(pk=reservation.pk)
    if res.status != Reservation.Status.ACTIVE:
        raise ValidationError("Only active reservations can be cancelled.")
    res.status = Reservation.Status.CANCELLED
    res.closed_at = timezone.now()
    if reason:
        res.notes = (res.notes + f"\nCancelled: {reason}").strip()
    res.save()
    _release_unit(res)
    return res


def expire_reservations(now=None):
    now = now or timezone.now()
    count = 0
    for res in Reservation.objects.filter(status=Reservation.Status.ACTIVE, expires_at__lte=now):
        with transaction.atomic():
            locked = Reservation.objects.select_for_update().get(pk=res.pk)
            if locked.status != Reservation.Status.ACTIVE:
                continue
            locked.status = Reservation.Status.EXPIRED
            locked.closed_at = now
            locked.save(update_fields=["status", "closed_at"])
            _release_unit(locked)
            count += 1
    return count
