from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone

from config.storage import private_storage
from config.validators import validate_document_upload


class Channel(models.TextChoices):
    IN_APP = "in_app", "In-app"
    EMAIL = "email", "Email"
    SMS = "sms", "SMS"
    WHATSAPP = "whatsapp", "WhatsApp"


class NotificationTemplate(models.Model):
    """Editable message wording. Placeholders use {name} syntax, e.g. {first_name},
    {amount}, {due_date}, {balance}, {link}, {company}."""

    key = models.CharField(max_length=50, unique=True)
    name = models.CharField(max_length=100)
    subject = models.CharField(max_length=150)
    body = models.TextField(help_text="Email / in-app body")
    short_body = models.CharField(max_length=320, help_text="SMS / WhatsApp text (keep it short, no sensitive data)")
    is_active = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["key"]

    def __str__(self):
        return self.name


class Notification(models.Model):
    class Status(models.TextChoices):
        QUEUED = "queued", "Queued"
        SENT = "sent", "Sent to provider"
        DELIVERED = "delivered", "Delivered (in-app)"
        LOGGED = "logged", "Logged only – provider not configured"
        FAILED = "failed", "Failed"
        SKIPPED = "skipped", "Skipped"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.CASCADE, related_name="notifications"
    )
    tenant = models.ForeignKey(
        "tenancies.Tenant", null=True, blank=True, on_delete=models.CASCADE, related_name="notifications"
    )
    channel = models.CharField(max_length=10, choices=Channel.choices)
    to_address = models.CharField(max_length=150, blank=True)
    template_key = models.CharField(max_length=50, db_index=True)
    subject = models.CharField(max_length=200)
    body = models.TextField()
    link = models.CharField(max_length=300, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.QUEUED, db_index=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    last_error = models.CharField(max_length=500, blank=True)
    next_attempt_at = models.DateTimeField(default=timezone.now, db_index=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    read_at = models.DateTimeField(null=True, blank=True, help_text="Only set for in-app notifications opened in the portal")
    dedupe_key = models.CharField(max_length=150, null=True, blank=True, unique=True)
    related_type = models.CharField(max_length=40, blank=True)
    related_id = models.CharField(max_length=40, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["status", "next_attempt_at"])]

    def __str__(self):
        return f"{self.channel} {self.template_key} → {self.to_address or self.user_id}"


class NotificationAttempt(models.Model):
    notification = models.ForeignKey(Notification, on_delete=models.CASCADE, related_name="delivery_attempts")
    attempted_at = models.DateTimeField(auto_now_add=True)
    provider = models.CharField(max_length=40)
    success = models.BooleanField(default=False)
    provider_message_id = models.CharField(max_length=120, blank=True)
    error = models.CharField(max_length=500, blank=True)

    class Meta:
        ordering = ["-attempted_at"]


class Announcement(models.Model):
    class Priority(models.TextChoices):
        LOW = "low", "Low"
        NORMAL = "normal", "Normal"
        HIGH = "high", "High"
        URGENT = "urgent", "Urgent"

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        SCHEDULED = "scheduled", "Scheduled"
        PUBLISHED = "published", "Published"
        ARCHIVED = "archived", "Archived"

    class Audience(models.TextChoices):
        ALL_TENANTS = "all_tenants", "All active tenants (portfolio)"
        PROPERTIES = "properties", "Tenants in selected properties"
        BUILDINGS = "buildings", "Tenants in selected buildings / blocks"
        TENANTS = "tenants", "Specific tenants"
        STAFF = "staff", "Selected staff members"

    title = models.CharField(max_length=200)
    body = models.TextField()
    priority = models.CharField(max_length=10, choices=Priority.choices, default=Priority.NORMAL)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT, db_index=True)
    audience = models.CharField(max_length=15, choices=Audience.choices, default=Audience.PROPERTIES)
    properties = models.ManyToManyField("properties.Property", blank=True, related_name="announcements")
    buildings = models.ManyToManyField("properties.Building", blank=True, related_name="announcements")
    tenants = models.ManyToManyField("tenancies.Tenant", blank=True, related_name="targeted_announcements")
    staff = models.ManyToManyField(settings.AUTH_USER_MODEL, blank=True, related_name="staff_announcements")
    requires_acknowledgement = models.BooleanField(default=False)
    action_text = models.CharField(max_length=200, blank=True, help_text="e.g. 'Please sign the updated house rules'")
    related_document = models.ForeignKey(
        "documents.Document", null=True, blank=True, on_delete=models.SET_NULL, related_name="announcements"
    )
    send_email = models.BooleanField(default=True)
    send_sms = models.BooleanField(default=False)
    send_whatsapp = models.BooleanField(default=False)
    publish_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    published_at = models.DateTimeField(null=True, blank=True)
    is_template = models.BooleanField(default=False, help_text="Reusable notice that can be copied")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.title


class AnnouncementAttachment(models.Model):
    announcement = models.ForeignKey(Announcement, on_delete=models.CASCADE, related_name="attachments")
    file = models.FileField(
        upload_to="announcements/%Y/%m/", storage=private_storage, validators=[validate_document_upload]
    )
    original_name = models.CharField(max_length=200)
    uploaded_at = models.DateTimeField(auto_now_add=True)


class AnnouncementRecipient(models.Model):
    """Per-recipient record. In-app availability, portal open and explicit
    acknowledgement are tracked separately; external channel delivery is in
    the Notification log."""

    announcement = models.ForeignKey(Announcement, on_delete=models.CASCADE, related_name="recipients")
    tenant = models.ForeignKey(
        "tenancies.Tenant", null=True, blank=True, on_delete=models.CASCADE, related_name="announcement_receipts"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.CASCADE, related_name="announcement_receipts"
    )
    property = models.ForeignKey("properties.Property", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    delivered_at = models.DateTimeField(auto_now_add=True)
    opened_at = models.DateTimeField(null=True, blank=True)
    acknowledged_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["announcement", "tenant"], condition=Q(tenant__isnull=False), name="uniq_ann_tenant"
            ),
            models.UniqueConstraint(
                fields=["announcement", "user"], condition=Q(tenant__isnull=True), name="uniq_ann_staff_user"
            ),
        ]
