"""Rent ledger logic.

The balance of a tenancy is always *derived*:

    balance = sum(debit charges) - sum(credit adjustments) - sum(verified payments)

Positive = amount owed, negative = credit in the tenant's favour. Payments and
credits are allocated to debit charges oldest-due-first to work out what is
overdue. Pending or rejected payments never reduce the balance.
"""
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from accounts.models import CompanySettings
from tenancies.models import Tenancy

from .models import Charge, Payment

ZERO = Decimal("0.00")


def month_start(d):
    return d.replace(day=1)


def add_months(d, n):
    m = d.month - 1 + n
    return d.replace(year=d.year + m // 12, month=m % 12 + 1, day=1)


def due_date_for(period, due_day, start_date=None):
    due = period.replace(day=min(max(due_day, 1), 28))
    if start_date and due < start_date:
        due = start_date
    return due


# --------------------------------------------------------------------------- charges
def generate_charges_for_tenancy(tenancy, as_of=None, user=None):
    """Create any missing monthly rent / service charges (and the deposit) up to
    and including the month of `as_of`. Safe to run repeatedly."""
    as_of = as_of or timezone.localdate()
    if tenancy.status not in Tenancy.CURRENT_STATUSES and not tenancy.actual_move_out:
        return 0
    last_day = as_of
    if tenancy.actual_move_out:
        last_day = min(last_day, tenancy.actual_move_out)
    created = 0
    first_period = month_start(tenancy.start_date)

    def _create(**kwargs):
        nonlocal created
        # A voided charge for the period also counts: staff voided it on purpose,
        # so the scheduler must not silently re-create it.
        exists = Charge.objects.filter(tenancy=tenancy, kind=kwargs["kind"], period=kwargs["period"]).exists()
        if exists:
            return
        try:
            with transaction.atomic():
                Charge.objects.create(tenancy=tenancy, property_id=tenancy.property_id, created_by=user, **kwargs)
                created += 1
        except IntegrityError:
            pass  # created concurrently by another worker

    if tenancy.charge_deposit and tenancy.deposit_amount > 0:
        _create(
            kind=Charge.Kind.DEPOSIT, period=first_period, amount=tenancy.deposit_amount,
            due_date=tenancy.start_date, description="Security deposit",
        )

    period = first_period
    while period <= month_start(last_day):
        due = due_date_for(period, tenancy.rent_due_day, tenancy.start_date)
        label = period.strftime("%B %Y")
        if tenancy.monthly_rent > 0:
            _create(kind=Charge.Kind.RENT, period=period, amount=tenancy.monthly_rent, due_date=due,
                    description=f"Rent – {label}")
        if tenancy.service_charge > 0:
            _create(kind=Charge.Kind.SERVICE, period=period, amount=tenancy.service_charge, due_date=due,
                    description=f"Service charge – {label}")
        period = add_months(period, 1)
    return created


def generate_all_charges(as_of=None):
    total = 0
    for tenancy in Tenancy.objects.filter(status__in=Tenancy.CURRENT_STATUSES):
        total += generate_charges_for_tenancy(tenancy, as_of)
    return total


# --------------------------------------------------------------------------- balances
@dataclass
class AccountSummary:
    total_charged: Decimal
    total_credits: Decimal
    total_paid: Decimal
    balance: Decimal
    due_now: Decimal
    overdue_amount: Decimal
    overdue_since: date | None
    days_overdue: int
    next_due_date: date | None
    next_due_amount: Decimal
    status: str  # credit | paid | upcoming | due | overdue
    pending_payments: Decimal

    def as_dict(self):
        return asdict(self)


def summarize(tenancy, charges, payments, as_of=None):
    """Pure calculation from already-loaded charges/payments."""
    as_of = as_of or timezone.localdate()
    grace = timedelta(days=tenancy.grace_days or 0)
    active_charges = [c for c in charges if not c.voided]
    debits = sorted((c for c in active_charges if c.kind != Charge.Kind.CREDIT), key=lambda c: (c.due_date, c.id or 0))
    credits = sum((c.amount for c in active_charges if c.kind == Charge.Kind.CREDIT), ZERO)
    paid = sum((p.amount for p in payments if p.status == Payment.Status.VERIFIED), ZERO)
    pending = sum((p.amount for p in payments if p.status == Payment.Status.PENDING), ZERO)
    charged = sum((c.amount for c in debits), ZERO)

    available = credits + paid
    due_now = overdue = next_amount = ZERO
    overdue_since = next_due = None
    for c in debits:
        covered = min(available, c.amount)
        available -= covered
        uncovered = c.amount - covered
        if uncovered <= 0:
            continue
        if c.due_date <= as_of:
            due_now += uncovered
        if c.due_date + grace < as_of:
            overdue += uncovered
            overdue_since = overdue_since or c.due_date
        if c.due_date > as_of and next_due is None:
            next_due, next_amount = c.due_date, uncovered

    balance = charged - credits - paid
    if next_due is None and tenancy.status in Tenancy.CURRENT_STATUSES:
        nxt = add_months(month_start(as_of), 1)
        this_due = due_date_for(month_start(as_of), tenancy.rent_due_day)
        next_due = this_due if this_due > as_of else due_date_for(nxt, tenancy.rent_due_day)
        next_amount = tenancy.monthly_rent + tenancy.service_charge

    if balance < 0:
        status = "credit"
    elif overdue > 0:
        status = "overdue"
    elif due_now > 0:
        status = "due"
    elif balance == 0 and charged > 0:
        status = "paid"
    else:
        status = "upcoming" if balance > 0 else "paid"

    return AccountSummary(
        total_charged=charged, total_credits=credits, total_paid=paid, balance=balance,
        due_now=due_now, overdue_amount=overdue, overdue_since=overdue_since,
        days_overdue=(as_of - overdue_since).days if overdue_since else 0,
        next_due_date=next_due, next_due_amount=next_amount, status=status, pending_payments=pending,
    )


def account_summary(tenancy, as_of=None):
    return summarize(tenancy, list(tenancy.charges.all()), list(tenancy.payments.all()), as_of)


def bulk_summaries(tenancies, as_of=None):
    """Summaries for many tenancies using two queries."""
    tenancies = list(tenancies)
    ids = [t.id for t in tenancies]
    charges, payments = defaultdict(list), defaultdict(list)
    for c in Charge.objects.filter(tenancy_id__in=ids, voided=False):
        charges[c.tenancy_id].append(c)
    for p in Payment.objects.filter(tenancy_id__in=ids).exclude(status=Payment.Status.REJECTED):
        payments[p.tenancy_id].append(p)
    return {t.id: summarize(t, charges[t.id], payments[t.id], as_of) for t in tenancies}


def outstanding_through(tenancy, through_date):
    """Amount still unpaid for charges due on or before `through_date`."""
    s = account_summary(tenancy, as_of=through_date)
    return s.due_now


def suggested_payment_amount(tenancy):
    s = account_summary(tenancy)
    if s.balance > 0:
        return s.balance
    return tenancy.monthly_rent + tenancy.service_charge


# --------------------------------------------------------------------------- payments
def assign_receipt_number(payment):
    if payment.receipt_number:
        return payment.receipt_number
    prefix = CompanySettings.load().receipt_prefix or "RCT"
    payment.receipt_number = f"{prefix}-{payment.paid_on.year}-{payment.pk:06d}"
    return payment.receipt_number


@transaction.atomic
def verify_payment(payment, user=None):
    payment = Payment.objects.select_for_update().get(pk=payment.pk)
    if payment.status == Payment.Status.VERIFIED:
        return payment
    payment.status = Payment.Status.VERIFIED
    payment.verified_by = user
    payment.verified_at = timezone.now()
    assign_receipt_number(payment)
    payment.save()
    transaction.on_commit(lambda: notify_payment_received(payment.pk))
    return payment


def notify_payment_received(payment_id):
    from communications.services import notify_tenant

    payment = Payment.objects.select_related("tenancy__tenant", "tenancy__unit", "property").get(pk=payment_id)
    if payment.status != Payment.Status.VERIFIED:
        return
    tenancy = payment.tenancy
    summary = account_summary(tenancy)
    notify_tenant(
        tenancy.tenant,
        "payment_received",
        {
            "amount": f"{payment.amount:,.2f}",
            "receipt": payment.receipt_number,
            "balance": f"{max(summary.balance, ZERO):,.2f}",
            "property": payment.property.name,
            "simulated_note": " [SIMULATED DEMO PAYMENT – no money was transferred]" if payment.is_simulated else "",
        },
        link="/tenant/payments",
        dedupe=f"payment:{payment.pk}",
        related=("Payment", payment.pk),
    )


def current_tenancy_q():
    return Q(status__in=Tenancy.CURRENT_STATUSES)
