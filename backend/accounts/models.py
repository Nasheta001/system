from django.conf import settings
from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models
from django.utils import timezone

from config.validators import validate_phone


class Role(models.TextChoices):
    ADMIN = "admin", "Company administrator"
    LANDLORD = "landlord", "Landlord / portfolio owner"
    MANAGER = "manager", "Property manager"
    CARETAKER = "caretaker", "Caretaker"
    TENANT = "tenant", "Tenant"


STAFF_ROLES = {Role.ADMIN, Role.LANDLORD, Role.MANAGER, Role.CARETAKER}
PORTFOLIO_ROLES = {Role.ADMIN, Role.LANDLORD}


class UserManager(BaseUserManager):
    use_in_migrations = True

    def _create_user(self, email, password, **extra):
        if not email:
            raise ValueError("Email is required")
        email = self.normalize_email(email).lower()
        user = self.model(email=email, **extra)
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra):
        extra.setdefault("is_staff", False)
        extra.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra)

    def create_superuser(self, email, password=None, **extra):
        extra.setdefault("is_staff", True)
        extra.setdefault("is_superuser", True)
        extra.setdefault("role", Role.ADMIN)
        return self._create_user(email, password, **extra)


class User(AbstractUser):
    """Single user table for staff and tenants. Email is the login identifier."""

    username = None
    email = models.EmailField(unique=True)
    phone = models.CharField(max_length=20, blank=True, validators=[validate_phone])
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.TENANT, db_index=True)
    must_change_password = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    objects = UserManager()

    class Meta:
        ordering = ["first_name", "last_name"]

    def __str__(self):
        return self.get_full_name() or self.email

    @property
    def is_staff_member(self):
        return self.role in STAFF_ROLES

    @property
    def is_tenant(self):
        return self.role == Role.TENANT

    @property
    def has_portfolio_access(self):
        return self.role in PORTFOLIO_ROLES or self.is_superuser


class PropertyAssignment(models.Model):
    """Links a staff member (manager/caretaker) to a property they may access."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="assignments")
    property = models.ForeignKey("properties.Property", on_delete=models.CASCADE, related_name="staff_assignments")
    is_primary_contact = models.BooleanField(default=False)
    assigned_at = models.DateTimeField(auto_now_add=True)
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "property"], name="uniq_assignment")]

    def __str__(self):
        return f"{self.user} → {self.property}"


class StaffProfile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="staff_profile")
    job_title = models.CharField(max_length=100, blank=True)
    alternative_phone = models.CharField(max_length=20, blank=True)
    notes = models.TextField(blank=True)


class CompanySettings(models.Model):
    """Singleton row with company branding and operational defaults."""

    name = models.CharField(max_length=150, default="Your Property Company")
    tagline = models.CharField(max_length=200, blank=True)
    about = models.TextField(blank=True)
    phone = models.CharField(max_length=30, blank=True)
    whatsapp = models.CharField(max_length=30, blank=True)
    email = models.EmailField(blank=True)
    address = models.CharField(max_length=255, blank=True)
    currency = models.CharField(max_length=3, default="KES")
    default_grace_days = models.PositiveSmallIntegerField(default=5)
    reservation_expiry_days = models.PositiveSmallIntegerField(default=3)
    receipt_prefix = models.CharField(max_length=10, default="RCT")
    # Rent paid by M-Pesa "Send Money" to the landlord's own phone number. This is a
    # person-to-person transfer: Daraja cannot confirm it, so every tenant report is
    # verified by staff against the M-Pesa statement before it counts.
    rent_receiving_phone = models.CharField(
        max_length=16, blank=True, help_text="Landlord's M-Pesa number for Send Money rent payments (+2547…/+2541…)")
    rent_receiving_name = models.CharField(
        max_length=100, blank=True, help_text="Name M-Pesa shows for that number, so tenants can check the recipient")
    rent_phone_payments_enabled = models.BooleanField(default=False)
    privacy_notice = models.TextField(blank=True)
    faq = models.JSONField(default=list, blank=True, help_text="List of {question, answer} items")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "Company settings"

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def __str__(self):
        return self.name


class AuditLog(models.Model):
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="audit_entries"
    )
    action = models.CharField(max_length=60, db_index=True)
    object_type = models.CharField(max_length=60, blank=True, db_index=True)
    object_id = models.CharField(max_length=40, blank=True)
    summary = models.CharField(max_length=500)
    changes = models.JSONField(default=dict, blank=True)
    property = models.ForeignKey(
        "properties.Property", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.created_at:%Y-%m-%d %H:%M} {self.action} {self.summary}"


class Invitation(models.Model):
    """A single-use, expiring invitation to create an account.

    Only a SHA-256 hash of the token is stored, so a database leak does not
    reveal usable links. Staff invitations carry the role and property
    assignments; tenant invitations are bound to an existing tenant record and
    current tenancy, re-checked when the invitation is accepted.
    """

    class Kind(models.TextChoices):
        STAFF = "staff", "Staff"
        TENANT = "tenant", "Tenant"

    kind = models.CharField(max_length=10, choices=Kind.choices)
    email = models.EmailField(db_index=True)
    first_name = models.CharField(max_length=150, blank=True)
    last_name = models.CharField(max_length=150, blank=True)
    phone = models.CharField(max_length=20, blank=True, validators=[validate_phone])
    role = models.CharField(max_length=20, choices=Role.choices)
    job_title = models.CharField(max_length=100, blank=True)
    property_ids = models.JSONField(default=list, blank=True)
    tenant = models.ForeignKey("tenancies.Tenant", null=True, blank=True, on_delete=models.CASCADE,
                               related_name="invitations")
    tenancy = models.ForeignKey("tenancies.Tenancy", null=True, blank=True, on_delete=models.SET_NULL,
                                related_name="+")
    token_hash = models.CharField(max_length=64, unique=True)
    expires_at = models.DateTimeField()
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                   related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    sent_count = models.PositiveSmallIntegerField(default=1)
    accepted_at = models.DateTimeField(null=True, blank=True)
    accepted_user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                      related_name="+")
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoked_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                   related_name="+")
    revoke_reason = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["email"], condition=models.Q(accepted_at__isnull=True,
                                                                         revoked_at__isnull=True),
                                    name="one_open_invitation_per_email"),
        ]

    def __str__(self):
        return f"{self.get_kind_display()} invitation for {self.email} ({self.status})"

    @property
    def status(self):
        if self.accepted_at:
            return "accepted"
        if self.revoked_at:
            return "revoked"
        if self.expires_at <= timezone.now():
            return "expired"
        return "pending"

    @property
    def is_open(self):
        return self.status == "pending"
