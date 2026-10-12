import builtins
from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q

POSITIVE = [MinValueValidator(Decimal("0.01"))]


class ReminderSchedule(models.Model):
    """A configurable sequence of rent reminders relative to the due date."""

    name = models.CharField(max_length=100, unique=True)
    is_default = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-is_default", "name"]

    def __str__(self):
        return self.name

    @classmethod
    def default(cls):
        return cls.objects.filter(is_default=True).first()


class ReminderStep(models.Model):
    class Kind(models.TextChoices):
        UPCOMING = "rent_upcoming", "Upcoming payment reminder"
        DUE = "rent_due", "Payment due today"
        OVERDUE = "rent_overdue", "Overdue reminder"

    schedule = models.ForeignKey(ReminderSchedule, on_delete=models.CASCADE, related_name="steps")
    offset_days = models.SmallIntegerField(help_text="Days relative to the due date (negative = before)")
    kind = models.CharField(max_length=20, choices=Kind.choices)
    alert_management = models.BooleanField(default=False, help_text="Also create a management follow-up alert")
    custom_message = models.TextField(blank=True, help_text="Optional wording overriding the template body")

    class Meta:
        ordering = ["offset_days"]
        constraints = [models.UniqueConstraint(fields=["schedule", "offset_days"], name="uniq_step_offset")]

    def __str__(self):
        return f"{self.schedule}: {self.offset_days:+d} days ({self.kind})"


class Charge(models.Model):
    """A debit (rent, service charge, deposit, other agreed charge) or a credit
    adjustment on a tenancy account. Balances are always derived from charges
    and verified payments – never stored as a mutable number."""

    class Kind(models.TextChoices):
        RENT = "rent", "Rent"
        SERVICE = "service", "Service charge"
        DEPOSIT = "deposit", "Deposit"
        UTILITY = "utility", "Utility"
        OTHER = "other", "Other agreed charge"
        CREDIT = "credit", "Credit / adjustment"

    tenancy = models.ForeignKey("tenancies.Tenancy", on_delete=models.PROTECT, related_name="charges")
    property = models.ForeignKey("properties.Property", on_delete=models.PROTECT, related_name="charges")
    kind = models.CharField(max_length=10, choices=Kind.choices, db_index=True)
    description = models.CharField(max_length=200)
    period = models.DateField(null=True, blank=True, help_text="First day of the billing month")
    amount = models.DecimalField(max_digits=12, decimal_places=2, validators=POSITIVE)
    due_date = models.DateField(db_index=True)
    voided = models.BooleanField(default=False)
    void_reason = models.CharField(max_length=255, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["due_date", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["tenancy", "kind", "period"],
                condition=Q(voided=False, period__isnull=False),
                name="uniq_periodic_charge",
            )
        ]

    @builtins.property
    def is_credit(self):
        return self.kind == self.Kind.CREDIT

    def __str__(self):
        return f"{self.description} {self.amount}"


class Payment(models.Model):
    class Method(models.TextChoices):
        MPESA = "mpesa", "M-Pesa"
        MPESA_SIMULATED = "mpesa_simulated", "M-Pesa (SIMULATED – demo only)"
        CASH = "cash", "Cash"
        BANK = "bank", "Bank transfer / deposit"
        CHEQUE = "cheque", "Cheque"
        MPESA_MANUAL = "mpesa_manual", "M-Pesa (recorded manually)"
        MPESA_PHONE = "mpesa_phone", "M-Pesa Send Money to landlord's number"
        OTHER = "other", "Other"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending verification"
        VERIFIED = "verified", "Verified"
        REJECTED = "rejected", "Rejected"

    class Source(models.TextChoices):
        STK = "stk", "M-Pesa STK Push"
        MANUAL = "manual", "Recorded by staff"
        TENANT = "tenant", "Reported by tenant (awaiting staff check)"

    tenancy = models.ForeignKey("tenancies.Tenancy", on_delete=models.PROTECT, related_name="payments")
    property = models.ForeignKey("properties.Property", on_delete=models.PROTECT, related_name="payments")
    amount = models.DecimalField(max_digits=12, decimal_places=2, validators=POSITIVE)
    currency = models.CharField(max_length=3, default="KES")
    method = models.CharField(max_length=20, choices=Method.choices)
    source = models.CharField(max_length=10, choices=Source.choices, default=Source.MANUAL)
    reference = models.CharField(max_length=60, blank=True, help_text="Bank / M-Pesa / cheque reference")
    paid_on = models.DateField()
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING, db_index=True)
    is_simulated = models.BooleanField(default=False)
    mpesa_receipt = models.CharField(max_length=30, null=True, blank=True, unique=True)
    receipt_number = models.CharField(max_length=30, null=True, blank=True, unique=True)
    notes = models.CharField(max_length=500, blank=True)
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    verified_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-paid_on", "-id"]
        indexes = [models.Index(fields=["property", "status", "paid_on"])]

    def __str__(self):
        return f"{self.receipt_number or 'Payment'} {self.amount}"


class MpesaTransaction(models.Model):
    """One STK Push attempt. A Payment is only created after a verified
    successful callback (or a confirmed STK query)."""

    class Status(models.TextChoices):
        PENDING = "pending", "Awaiting customer"
        SUCCESS = "success", "Successful"
        FAILED = "failed", "Failed"
        CANCELLED = "cancelled", "Cancelled by customer"
        TIMEOUT = "timeout", "Timed out"

    FINAL_STATUSES = (Status.SUCCESS, Status.FAILED, Status.CANCELLED, Status.TIMEOUT)

    tenancy = models.ForeignKey("tenancies.Tenancy", on_delete=models.PROTECT, related_name="mpesa_transactions")
    initiated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    phone = models.CharField(max_length=15)
    amount = models.DecimalField(max_digits=12, decimal_places=2, validators=POSITIVE)
    account_reference = models.CharField(max_length=20)
    merchant_request_id = models.CharField(max_length=60, blank=True)
    checkout_request_id = models.CharField(max_length=60, unique=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING, db_index=True)
    result_code = models.CharField(max_length=10, blank=True)
    result_desc = models.CharField(max_length=255, blank=True)
    mpesa_receipt = models.CharField(max_length=30, blank=True)
    is_simulated = models.BooleanField(default=False)
    callback_count = models.PositiveIntegerField(default=0)
    raw_callback = models.JSONField(default=dict, blank=True)
    payment = models.OneToOneField(Payment, null=True, blank=True, on_delete=models.SET_NULL, related_name="transaction")
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    last_queried_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]


class ReminderLog(models.Model):
    """Ensures each reminder step fires at most once per tenancy per due date."""

    tenancy = models.ForeignKey("tenancies.Tenancy", on_delete=models.CASCADE, related_name="reminder_logs")
    step = models.ForeignKey(ReminderStep, null=True, on_delete=models.SET_NULL, related_name="logs")
    kind = models.CharField(max_length=20)
    offset_days = models.SmallIntegerField()
    due_date = models.DateField()
    balance_at_send = models.DecimalField(max_digits=12, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["tenancy", "due_date", "offset_days"], name="uniq_reminder_per_step")
        ]


class FollowUpTask(models.Model):
    """Management follow-up created by reminder escalations or other events."""

    class Status(models.TextChoices):
        OPEN = "open", "Open"
        DONE = "done", "Done"
        DISMISSED = "dismissed", "Dismissed"

    property = models.ForeignKey("properties.Property", on_delete=models.CASCADE, related_name="follow_ups")
    tenancy = models.ForeignKey(
        "tenancies.Tenancy", null=True, blank=True, on_delete=models.CASCADE, related_name="follow_ups"
    )
    title = models.CharField(max_length=200)
    details = models.TextField(blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.OPEN, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    closed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
