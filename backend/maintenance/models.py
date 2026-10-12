import os
import secrets
import uuid

from django.conf import settings
from django.db import models

from config.storage import private_storage
from config.validators import validate_document_upload


def attachment_path(instance, filename):
    ext = os.path.splitext(filename)[1].lower()
    return f"maintenance/{instance.request_id}/{uuid.uuid4().hex}{ext}"


class MaintenanceRequest(models.Model):
    class Category(models.TextChoices):
        PLUMBING = "plumbing", "Plumbing"
        ELECTRICAL = "electrical", "Electrical"
        WATER = "water", "Water supply"
        SECURITY = "security", "Security / locks"
        STRUCTURAL = "structural", "Structural / walls / roof"
        APPLIANCES = "appliances", "Fixtures & appliances"
        CLEANING = "cleaning", "Cleaning / waste"
        PEST = "pest", "Pest control"
        OTHER = "other", "Other"

    class Urgency(models.TextChoices):
        LOW = "low", "Low"
        NORMAL = "normal", "Normal"
        HIGH = "high", "High"
        EMERGENCY = "emergency", "Emergency"

    class Status(models.TextChoices):
        SUBMITTED = "submitted", "Submitted"
        REVIEWED = "reviewed", "Reviewed"
        ASSIGNED = "assigned", "Assigned"
        IN_PROGRESS = "in_progress", "In progress"
        AWAITING_PARTS = "awaiting_parts", "Awaiting parts"
        COMPLETED = "completed", "Completed"
        CLOSED = "closed", "Closed"
        CANCELLED = "cancelled", "Cancelled"

    OPEN_STATUSES = ("submitted", "reviewed", "assigned", "in_progress", "awaiting_parts")

    reference = models.CharField(max_length=20, unique=True, editable=False)
    property = models.ForeignKey("properties.Property", on_delete=models.PROTECT, related_name="maintenance_requests")
    unit = models.ForeignKey(
        "properties.Unit", null=True, blank=True, on_delete=models.PROTECT, related_name="maintenance_requests"
    )
    tenant = models.ForeignKey(
        "tenancies.Tenant", null=True, blank=True, on_delete=models.PROTECT, related_name="maintenance_requests"
    )
    tenancy = models.ForeignKey(
        "tenancies.Tenancy", null=True, blank=True, on_delete=models.PROTECT, related_name="maintenance_requests"
    )
    reported_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    title = models.CharField(max_length=150)
    description = models.TextField(max_length=4000)
    category = models.CharField(max_length=12, choices=Category.choices, default=Category.OTHER)
    urgency = models.CharField(max_length=10, choices=Urgency.choices, default=Urgency.NORMAL, db_index=True)
    status = models.CharField(max_length=15, choices=Status.choices, default=Status.SUBMITTED, db_index=True)
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="maintenance_assigned"
    )
    resolution_notes = models.TextField(blank=True, help_text="Shown to the tenant once completed")
    completed_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def save(self, *args, **kwargs):
        if not self.reference:
            ref = f"MR-{secrets.token_hex(3).upper()}"
            while MaintenanceRequest.objects.filter(reference=ref).exists():
                ref = f"MR-{secrets.token_hex(3).upper()}"
            self.reference = ref
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.reference} {self.title}"


class MaintenanceUpdate(models.Model):
    request = models.ForeignKey(MaintenanceRequest, on_delete=models.CASCADE, related_name="updates")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    message = models.TextField(blank=True, max_length=4000)
    is_internal = models.BooleanField(default=False, help_text="Internal notes are never shown to tenants")
    status_from = models.CharField(max_length=15, blank=True)
    status_to = models.CharField(max_length=15, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]


class MaintenanceAttachment(models.Model):
    request = models.ForeignKey(MaintenanceRequest, on_delete=models.CASCADE, related_name="attachments")
    file = models.FileField(upload_to=attachment_path, storage=private_storage, validators=[validate_document_upload])
    original_name = models.CharField(max_length=200)
    is_internal = models.BooleanField(default=False)
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    uploaded_at = models.DateTimeField(auto_now_add=True)
