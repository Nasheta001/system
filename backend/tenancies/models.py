import builtins
from decimal import Decimal

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q

from config.fields import EncryptedTextField
from config.validators import validate_phone


class Tenant(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        FORMER = "former", "Former tenant"
        INACTIVE = "inactive", "Inactive"

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="tenant_profile"
    )
    first_name = models.CharField(max_length=80)
    last_name = models.CharField(max_length=80)
    email = models.EmailField(blank=True, db_index=True)
    phone = models.CharField(max_length=20, db_index=True, validators=[validate_phone])
    alternative_phone = models.CharField(max_length=20, blank=True, validators=[validate_phone])
    id_number = EncryptedTextField(blank=True, help_text="National ID / passport (restricted, encrypted at rest)")
    occupation = models.CharField(max_length=100, blank=True)
    emergency_contact_name = models.CharField(max_length=120, blank=True)
    emergency_contact_phone = models.CharField(max_length=20, blank=True, validators=[validate_phone])
    emergency_contact_relationship = models.CharField(max_length=50, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE, db_index=True)
    notify_sms = models.BooleanField(default=True)
    notify_email = models.BooleanField(default=True)
    notify_whatsapp = models.BooleanField(default=False)
    notes = models.TextField(blank=True, help_text="Internal staff notes – never shown to the tenant")
    data_consent_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["first_name", "last_name"]

    def __str__(self):
        return self.full_name

    @builtins.property
    def full_name(self):
        return f"{self.first_name} {self.last_name}".strip()

    def current_tenancy(self):
        return (
            self.tenancies.filter(status__in=Tenancy.CURRENT_STATUSES)
            .select_related("unit", "property", "unit__building")
            .order_by("-start_date")
            .first()
        )


class Tenancy(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        NOTICE = "notice", "Notice given"
        ENDED = "ended", "Ended"
        CANCELLED = "cancelled", "Cancelled"

    CURRENT_STATUSES = (Status.ACTIVE, Status.NOTICE)

    tenant = models.ForeignKey(Tenant, on_delete=models.PROTECT, related_name="tenancies")
    unit = models.ForeignKey("properties.Unit", on_delete=models.PROTECT, related_name="tenancies")
    property = models.ForeignKey("properties.Property", on_delete=models.PROTECT, related_name="tenancies")
    reservation = models.OneToOneField(
        "leasing.Reservation", null=True, blank=True, on_delete=models.SET_NULL, related_name="tenancy"
    )
    transferred_from = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL, related_name="transferred_to"
    )
    start_date = models.DateField()
    expected_end_date = models.DateField(null=True, blank=True)
    monthly_rent = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal("0"))])
    service_charge = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))
    deposit_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))
    charge_deposit = models.BooleanField(default=True, help_text="Add the deposit to the tenant's account at move-in")
    rent_due_day = models.PositiveSmallIntegerField(default=5, validators=[MinValueValidator(1), MaxValueValidator(28)])
    grace_days = models.PositiveSmallIntegerField(default=5)
    reminder_schedule = models.ForeignKey(
        "billing.ReminderSchedule", null=True, blank=True, on_delete=models.SET_NULL, related_name="tenancies"
    )
    reminders_enabled = models.BooleanField(default=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE, db_index=True)

    # Move-in
    move_in_inspection_notes = models.TextField(blank=True)
    # Move-out
    notice_date = models.DateField(null=True, blank=True)
    planned_move_out = models.DateField(null=True, blank=True)
    actual_move_out = models.DateField(null=True, blank=True)
    move_out_inspection_date = models.DateField(null=True, blank=True)
    move_out_inspection_notes = models.TextField(blank=True)
    deposit_deductions = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))
    deposit_deduction_notes = models.TextField(blank=True)
    deposit_applied_to_balance = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))
    deposit_refund_amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    deposit_reconciled_at = models.DateTimeField(null=True, blank=True)
    unit_available_from = models.DateField(null=True, blank=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-start_date"]
        verbose_name_plural = "tenancies"
        constraints = [
            models.UniqueConstraint(
                fields=["unit"], condition=Q(status__in=["active", "notice"]), name="one_current_tenancy_per_unit"
            ),
        ]
        indexes = [models.Index(fields=["property", "status"])]

    def __str__(self):
        return f"{self.tenant} @ {self.unit}"

    @builtins.property
    def is_current(self):
        return self.status in self.CURRENT_STATUSES
