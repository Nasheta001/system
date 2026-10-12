import secrets

from django.conf import settings
from django.db import models
from django.db.models import Q

from config.validators import validate_phone


def _reference(prefix):
    return f"{prefix}-{secrets.token_hex(4).upper()}"


class ViewingRequest(models.Model):
    class Status(models.TextChoices):
        NEW = "new", "New"
        CONTACTED = "contacted", "Contacted"
        SCHEDULED = "scheduled", "Viewing scheduled"
        COMPLETED = "completed", "Completed"
        CANCELLED = "cancelled", "Cancelled"

    property = models.ForeignKey("properties.Property", on_delete=models.CASCADE, related_name="viewing_requests")
    unit = models.ForeignKey(
        "properties.Unit", null=True, blank=True, on_delete=models.SET_NULL, related_name="viewing_requests"
    )
    full_name = models.CharField(max_length=120)
    phone = models.CharField(max_length=20, validators=[validate_phone])
    email = models.EmailField(blank=True)
    preferred_date = models.DateField(null=True, blank=True)
    message = models.TextField(blank=True, max_length=2000)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.NEW, db_index=True)
    scheduled_for = models.DateTimeField(null=True, blank=True)
    staff_notes = models.TextField(blank=True)
    handled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    consent_given = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]


class RentalApplication(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        UNDER_REVIEW = "under_review", "Under review"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"
        WITHDRAWN = "withdrawn", "Withdrawn"

    OPEN_STATUSES = (Status.PENDING, Status.UNDER_REVIEW, Status.APPROVED)

    reference = models.CharField(max_length=20, unique=True, editable=False)
    unit = models.ForeignKey("properties.Unit", on_delete=models.PROTECT, related_name="applications")
    property = models.ForeignKey("properties.Property", on_delete=models.PROTECT, related_name="applications")
    full_name = models.CharField(max_length=120)
    email = models.EmailField()
    phone = models.CharField(max_length=20, validators=[validate_phone])
    occupation = models.CharField(max_length=100, blank=True)
    employer = models.CharField(max_length=120, blank=True)
    household_size = models.PositiveSmallIntegerField(default=1)
    desired_move_in = models.DateField(null=True, blank=True)
    message = models.TextField(blank=True, max_length=3000)
    consent_given = models.BooleanField(default=False)
    status = models.CharField(max_length=15, choices=Status.choices, default=Status.PENDING, db_index=True)
    applicant_message = models.CharField(
        max_length=500, blank=True, help_text="Message shown to the applicant on status lookup"
    )
    internal_notes = models.TextField(blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def save(self, *args, **kwargs):
        if not self.reference:
            ref = _reference("APP")
            while RentalApplication.objects.filter(reference=ref).exists():
                ref = _reference("APP")
            self.reference = ref
        if self.unit_id and not self.property_id:
            self.property_id = self.unit.property_id
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.reference} {self.full_name}"


class Reservation(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        CONVERTED = "converted", "Converted to tenancy"
        EXPIRED = "expired", "Expired"
        CANCELLED = "cancelled", "Cancelled"

    unit = models.ForeignKey("properties.Unit", on_delete=models.PROTECT, related_name="reservations")
    property = models.ForeignKey("properties.Property", on_delete=models.PROTECT, related_name="reservations")
    application = models.ForeignKey(
        RentalApplication, null=True, blank=True, on_delete=models.SET_NULL, related_name="reservations"
    )
    holder_name = models.CharField(max_length=120)
    holder_email = models.EmailField(blank=True)
    holder_phone = models.CharField(max_length=20, validators=[validate_phone])
    expires_at = models.DateTimeField()
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE, db_index=True)
    release_to_status = models.CharField(
        max_length=12, default="available", help_text="Unit status to restore if the reservation lapses"
    )
    notes = models.TextField(blank=True)
    reserved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["unit"], condition=Q(status="active"), name="one_active_reservation_per_unit"),
        ]

    def __str__(self):
        return f"Reservation {self.unit} for {self.holder_name}"
