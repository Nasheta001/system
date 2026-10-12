import os
import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q

from config.storage import private_storage
from config.validators import validate_document_upload


def version_path(instance, filename):
    ext = os.path.splitext(filename)[1].lower()
    return f"documents/{instance.document_id}/{uuid.uuid4().hex}{ext}"


def signed_path(instance, filename):
    ext = os.path.splitext(filename)[1].lower()
    return f"signatures/{instance.document_id}/{uuid.uuid4().hex}{ext}"


class Document(models.Model):
    class Category(models.TextChoices):
        TENANCY_AGREEMENT = "tenancy_agreement", "Tenancy agreement"
        RULES = "rules", "Building rules"
        WASTE = "waste", "Waste disposal"
        WATER = "water", "Water arrangements"
        SECURITY = "security", "Security procedures"
        EMERGENCY = "emergency", "Emergency contacts"
        NOTICE = "notice", "General notice"
        INSPECTION = "inspection", "Inspection record"
        MOVE_IN = "move_in", "Move-in document"
        MOVE_OUT = "move_out", "Move-out document"
        STATEMENT = "statement", "Statement / receipt"
        OTHER = "other", "Other"

    class Workflow(models.TextChoices):
        INFO = "info", "Information only"
        ACKNOWLEDGE = "acknowledge", "Acknowledgement required"
        SIGNATURE = "signature", "Signature required"

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        APPROVED = "approved", "Approved"
        ARCHIVED = "archived", "Archived"

    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    category = models.CharField(max_length=20, choices=Category.choices, default=Category.OTHER, db_index=True)
    workflow = models.CharField(max_length=12, choices=Workflow.choices, default=Workflow.INFO)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT, db_index=True)
    is_library = models.BooleanField(default=False, help_text="Part of the standard rules & notices library")
    property = models.ForeignKey(
        "properties.Property", null=True, blank=True, on_delete=models.PROTECT, related_name="documents",
        help_text="Owning property; empty for company-wide documents",
    )
    tenant = models.ForeignKey(
        "tenancies.Tenant", null=True, blank=True, on_delete=models.PROTECT, related_name="private_documents",
        help_text="Set for documents that belong to one tenant (e.g. agreement)",
    )
    tenancy = models.ForeignKey(
        "tenancies.Tenancy", null=True, blank=True, on_delete=models.PROTECT, related_name="documents"
    )
    current_version = models.ForeignKey(
        "DocumentVersion", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self):
        return self.title


class DocumentVersion(models.Model):
    document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name="versions")
    version = models.PositiveIntegerField()
    file = models.FileField(upload_to=version_path, storage=private_storage, validators=[validate_document_upload])
    original_name = models.CharField(max_length=200)
    size = models.PositiveIntegerField(default=0)
    notes = models.CharField(max_length=300, blank=True)
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-version"]
        constraints = [models.UniqueConstraint(fields=["document", "version"], name="uniq_doc_version")]


class DocumentAssignment(models.Model):
    """Who may see a document: all tenants, a property, a building or a tenant."""

    class Scope(models.TextChoices):
        ALL_TENANTS = "all_tenants", "All active tenants"
        PROPERTY = "property", "Tenants of a property"
        BUILDING = "building", "Tenants of a building / block"
        TENANT = "tenant", "Specific tenant"

    document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name="assignments")
    scope = models.CharField(max_length=12, choices=Scope.choices)
    property = models.ForeignKey("properties.Property", null=True, blank=True, on_delete=models.CASCADE, related_name="+")
    building = models.ForeignKey("properties.Building", null=True, blank=True, on_delete=models.CASCADE, related_name="+")
    tenant = models.ForeignKey("tenancies.Tenant", null=True, blank=True, on_delete=models.CASCADE, related_name="+")
    due_date = models.DateField(null=True, blank=True)
    assigned_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    assigned_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-assigned_at"]


class DocumentAcknowledgement(models.Model):
    document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name="acknowledgements")
    version = models.ForeignKey(DocumentVersion, on_delete=models.CASCADE, related_name="acknowledgements")
    tenant = models.ForeignKey("tenancies.Tenant", on_delete=models.CASCADE, related_name="document_acknowledgements")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    acknowledged_at = models.DateTimeField(auto_now_add=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["version", "tenant"], name="uniq_doc_ack")]


class SignatureRequest(models.Model):
    """Signature workflow. Default method is 'upload': the tenant downloads the
    document, signs it physically (or with their own qualified e-signature tool)
    and uploads the signed copy for staff verification. The 'provider' method
    is a placeholder for an integrated e-signature service."""

    class Method(models.TextChoices):
        UPLOAD = "upload", "Download, sign and upload"
        PROVIDER = "provider", "External e-signature provider"

    class Status(models.TextChoices):
        PENDING = "pending", "Awaiting signature"
        SUBMITTED = "submitted", "Signed copy submitted"
        VERIFIED = "verified", "Verified by staff"
        REJECTED = "rejected", "Rejected – resubmit"
        CANCELLED = "cancelled", "Cancelled"

    document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name="signature_requests")
    version = models.ForeignKey(DocumentVersion, on_delete=models.PROTECT, related_name="signature_requests")
    tenant = models.ForeignKey("tenancies.Tenant", on_delete=models.CASCADE, related_name="signature_requests")
    method = models.CharField(max_length=10, choices=Method.choices, default=Method.UPLOAD)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING, db_index=True)
    provider = models.CharField(max_length=60, blank=True)
    provider_reference = models.CharField(max_length=120, blank=True)
    signed_file = models.FileField(
        upload_to=signed_path, storage=private_storage, validators=[validate_document_upload], blank=True
    )
    due_date = models.DateField(null=True, blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_notes = models.CharField(max_length=300, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["version", "tenant"],
                condition=Q(status__in=["pending", "submitted", "verified"]),
                name="uniq_open_signature_request",
            )
        ]
