"""Scheduled rent reminders.

For every current tenancy with reminders enabled, each step of its reminder
schedule fires once per rent due date (enforced by a unique ReminderLog row).
A step is skipped when nothing is owed, so reminders stop automatically once
the balance is settled. Reminders never threaten eviction or add penalties.
"""
import logging
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone

from accounts.models import Role, User
from tenancies.models import Tenancy

from .models import Charge, FollowUpTask, ReminderLog, ReminderSchedule, ReminderStep
from .services import account_summary

logger = logging.getLogger(__name__)

# How many days late a step may still fire if the worker was not running.
CATCH_UP_DAYS = 1


def _unit_label(t):
    return f"{t.unit.label}, {t.property.name}"


def run_reminders(as_of=None):
    from communications.services import notify_tenant, notify_user

    as_of = as_of or timezone.localdate()
    default = ReminderSchedule.default()
    sent = 0
    tenancies = Tenancy.objects.filter(
        status__in=Tenancy.CURRENT_STATUSES, reminders_enabled=True
    ).select_related("tenant", "unit", "unit__building", "property", "reminder_schedule")
    for tenancy in tenancies:
        schedule = tenancy.reminder_schedule or default
        if schedule is None:
            continue
        steps = list(schedule.steps.all())
        if not steps:
            continue
        rent_due_dates = set(
            tenancy.charges.filter(voided=False, kind__in=[Charge.Kind.RENT, Charge.Kind.SERVICE])
            .values_list("due_date", flat=True)
        )
        summary = None
        for step in steps:
            for lag in range(CATCH_UP_DAYS + 1):
                target_due = as_of - timedelta(days=step.offset_days + lag)
                if target_due in rent_due_dates or (step.offset_days < 0 and _upcoming_due(tenancy, target_due)):
                    break
            else:
                continue
            summary = summary or account_summary(tenancy, as_of)
            if step.kind == ReminderStep.Kind.OVERDUE:
                amount = summary.overdue_amount if summary.overdue_amount > 0 else summary.due_now
                if summary.balance <= 0 or amount <= 0:
                    continue
            elif step.kind == ReminderStep.Kind.DUE:
                amount = account_summary(tenancy, target_due).due_now
                if summary.balance <= 0 or amount <= 0:
                    continue
            else:  # upcoming – what will be owed on the due date
                if target_due in rent_due_dates:
                    amount = account_summary(tenancy, target_due).due_now
                else:  # next month's charge not generated yet
                    amount = summary.balance + tenancy.monthly_rent + tenancy.service_charge
                if amount <= 0:
                    continue
            try:
                with transaction.atomic():
                    ReminderLog.objects.create(
                        tenancy=tenancy, step=step, kind=step.kind, offset_days=step.offset_days,
                        due_date=target_due, balance_at_send=summary.balance,
                    )
            except IntegrityError:
                continue  # already sent for this due date
            context = {
                "amount": f"{amount:,.2f}",
                "due_date": (summary.overdue_since or target_due).strftime("%d %b %Y")
                if step.kind == ReminderStep.Kind.OVERDUE else target_due.strftime("%d %b %Y"),
                "unit": _unit_label(tenancy),
            }
            if step.custom_message:
                context["message"] = step.custom_message
            notify_tenant(
                tenancy.tenant, step.kind, context, link="/tenant/payments",
                dedupe=f"reminder:{tenancy.pk}:{target_due}:{step.offset_days}", related=("Tenancy", tenancy.pk),
            )
            sent += 1
            if step.alert_management:
                title = f"Overdue rent: {tenancy.tenant.full_name} ({_unit_label(tenancy)})"
                task = FollowUpTask.objects.create(
                    property=tenancy.property, tenancy=tenancy, title=title,
                    details=f"Outstanding KES {summary.balance:,.2f}; overdue {summary.days_overdue} days.",
                )
                managers = User.objects.filter(
                    is_active=True, role__in=[Role.MANAGER], assignments__property=tenancy.property
                ).distinct()
                for m in managers:
                    notify_user(m, "staff_alert", {"title": title, "message": task.details},
                                link=f"/management/tenants/{tenancy.tenant_id}", channels=("in_app",),
                                dedupe=f"followup:{task.pk}:{m.pk}")
    return sent


def _upcoming_due(tenancy, target_due):
    """For pre-due reminders the charge may not have been generated yet
    (e.g. reminder 3 days before the 1st). Check the configured due day."""
    return target_due.day == min(tenancy.rent_due_day, 28) and target_due >= tenancy.start_date


def ensure_default_schedule():
    schedule, created = ReminderSchedule.objects.get_or_create(name="Standard schedule", defaults={"is_default": True})
    if created or not schedule.steps.exists():
        for offset, kind, alert in [
            (-3, ReminderStep.Kind.UPCOMING, False),
            (0, ReminderStep.Kind.DUE, False),
            (3, ReminderStep.Kind.OVERDUE, False),
            (10, ReminderStep.Kind.OVERDUE, True),
        ]:
            ReminderStep.objects.get_or_create(schedule=schedule, offset_days=offset,
                                               defaults={"kind": kind, "alert_management": alert})
    if not ReminderSchedule.objects.filter(is_default=True).exists():
        schedule.is_default = True
        schedule.save(update_fields=["is_default"])
    return schedule
