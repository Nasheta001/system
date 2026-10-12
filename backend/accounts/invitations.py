"""Invitation-only account creation, and revoking access.

There is no public sign-up. Accounts come into existence only by:
  * the one-time initial administrator setup (when no administrator exists),
  * `manage.py createsuperuser` on the server, or
  * accepting an invitation created here.

Tokens are 256-bit random values. Only their SHA-256 hash is stored; the raw
token exists in the emailed link (as a URL fragment, so it never reaches
server or proxy access logs) and, in DEBUG only, in the API response.
"""
import hashlib
import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.password_validation import validate_password
from django.contrib.sessions.models import Session
from django.db import transaction
from django.utils import timezone

from .models import Invitation, PropertyAssignment, Role, STAFF_ROLES, StaffProfile, User

INVITE_PATH = "/account/accept-invite"


class InvitationError(Exception):
    pass


def hash_token(raw):
    return hashlib.sha256(str(raw).encode()).hexdigest()


def _new_token():
    raw = secrets.token_urlsafe(32)
    return raw, hash_token(raw)


def invite_link(raw):
    return f"{settings.FRONTEND_URL}{INVITE_PATH}#token={raw}"


def _expiry():
    return timezone.now() + timedelta(hours=settings.INVITATION_TTL_HOURS)


def dev_link(raw):
    """DEVELOPMENT ONLY: the raw link is returned to the inviting admin so the
    flow can be tested without an email provider. Never in production."""
    return invite_link(raw) if settings.DEBUG else None


def _send(inv, raw):
    from communications.services import notify_address

    hours = settings.INVITATION_TTL_HOURS
    ctx = {"first_name": inv.first_name or "there", "invite_link": invite_link(raw),
           "valid_for": f"{hours // 24} days" if hours % 24 == 0 and hours >= 48 else f"{hours} hours",
           "role": inv.get_role_display()}
    key = "tenant_invite" if inv.kind == Invitation.Kind.TENANT else "staff_invite"
    notify_address("email", inv.email, key, ctx, related=("invitation", inv.pk))
    if inv.kind == Invitation.Kind.TENANT and inv.phone:
        # The SMS only points to the email; secret links are not sent by SMS.
        notify_address("sms", inv.phone, key, ctx, related=("invitation", inv.pk))


def revoke_open_invitations(*, email=None, tenant=None, by=None, reason=""):
    qs = Invitation.objects.filter(accepted_at__isnull=True, revoked_at__isnull=True)
    if email:
        qs = qs.filter(email__iexact=email)
    elif tenant is not None:
        qs = qs.filter(tenant=tenant)
    else:
        return 0
    return qs.update(revoked_at=timezone.now(), revoked_by=by, revoke_reason=reason[:200])


def revoke_invitation(inv, by, reason="Revoked by an administrator"):
    if inv.accepted_at or inv.revoked_at:
        raise InvitationError("This invitation is no longer open.")
    inv.revoked_at = timezone.now()
    inv.revoked_by = by
    inv.revoke_reason = reason[:200]
    inv.save(update_fields=["revoked_at", "revoked_by", "revoke_reason"])
    return inv


# ------------------------------------------------------------------ staff
@transaction.atomic
def create_staff_invitation(*, email, role, by, first_name="", last_name="", phone="", job_title="",
                            property_ids=()):
    email = email.strip().lower()
    if role not in STAFF_ROLES:
        raise InvitationError("Choose a staff role.")
    if User.objects.filter(email__iexact=email).exists():
        raise InvitationError("A user with this email already exists.")
    revoke_open_invitations(email=email, by=by, reason="Replaced by a new invitation")
    raw, digest = _new_token()
    inv = Invitation.objects.create(
        kind=Invitation.Kind.STAFF, email=email, role=role, first_name=first_name, last_name=last_name, phone=phone,
        job_title=job_title, property_ids=sorted({int(p) for p in property_ids}), token_hash=digest,
        expires_at=_expiry(), created_by=by,
    )
    _send(inv, raw)
    return inv, raw


# ------------------------------------------------------------------ tenants
def tenant_eligibility(tenant):
    """Return the tenancy a portal invitation would be linked to, or raise.
    A tenant qualifies only with an email, no existing login and a current
    (active or notice) tenancy. Knowing an ID number is never enough."""
    from tenancies.models import Tenancy, Tenant

    if tenant.user_id:
        raise InvitationError("This tenant already has a portal account.")
    if not tenant.email:
        raise InvitationError("Add an email address for the tenant first.")
    if tenant.status != Tenant.Status.ACTIVE:
        raise InvitationError("Only current tenants can be invited to the portal.")
    tenancy = (tenant.tenancies.filter(status__in=Tenancy.CURRENT_STATUSES).order_by("-start_date").first())
    if tenancy is None:
        raise InvitationError("The tenant needs a current tenancy before they can be invited.")
    if User.objects.filter(email__iexact=tenant.email).exists():
        raise InvitationError("Another account already uses this email address.")
    return tenancy


@transaction.atomic
def create_tenant_invitation(tenant, by):
    tenancy = tenant_eligibility(tenant)
    revoke_open_invitations(email=tenant.email, by=by, reason="Replaced by a new invitation")
    revoke_open_invitations(tenant=tenant, by=by, reason="Replaced by a new invitation")
    raw, digest = _new_token()
    inv = Invitation.objects.create(
        kind=Invitation.Kind.TENANT, email=tenant.email.lower(), role=Role.TENANT, first_name=tenant.first_name,
        last_name=tenant.last_name, phone=tenant.phone, tenant=tenant, tenancy=tenancy, token_hash=digest,
        expires_at=_expiry(), created_by=by,
    )
    _send(inv, raw)
    return inv, raw


@transaction.atomic
def resend_invitation(inv, by):
    """Issue a fresh token (the previous link stops working) and a new expiry."""
    inv = Invitation.objects.select_for_update().get(pk=inv.pk)
    if inv.accepted_at or inv.revoked_at:
        raise InvitationError("This invitation is no longer open. Create a new one.")
    if inv.kind == Invitation.Kind.TENANT:
        inv.tenancy = tenant_eligibility(inv.tenant)
    raw, inv.token_hash = _new_token()
    inv.expires_at = _expiry()
    inv.sent_count += 1
    inv.save(update_fields=["token_hash", "expires_at", "sent_count", "tenancy"])
    _send(inv, raw)
    return inv, raw


# ------------------------------------------------------------------ accepting
def find_open_invitation(raw):
    if not raw or len(str(raw)) > 200:
        return None
    inv = Invitation.objects.select_related("tenant").filter(token_hash=hash_token(raw)).first()
    if inv is None or not inv.is_open:
        return None
    if inv.kind == Invitation.Kind.TENANT:
        try:
            tenant_eligibility(inv.tenant)
        except InvitationError:
            return None
    return inv


@transaction.atomic
def accept_invitation(raw, password):
    """Create the account described by the invitation. Role, email, tenant link
    and property assignments come from the stored invitation, never from the
    request."""
    from tenancies.models import Tenant

    inv = (Invitation.objects.select_for_update().filter(token_hash=hash_token(raw)).first()
           if raw and len(str(raw)) <= 200 else None)
    if inv is None or not inv.is_open:
        raise InvitationError("This invitation link is invalid, has expired or has already been used.")
    tenant = None
    if inv.kind == Invitation.Kind.TENANT:
        tenant = Tenant.objects.select_for_update().get(pk=inv.tenant_id)
        try:
            inv.tenancy = tenant_eligibility(tenant)
        except InvitationError as exc:
            raise InvitationError("This invitation is no longer valid. Please contact the management office.") from exc
        if tenant.email.lower() != inv.email:
            raise InvitationError("This invitation is no longer valid. Please contact the management office.")
    if User.objects.filter(email__iexact=inv.email).exists():
        raise InvitationError("An account with this email already exists. Sign in or reset your password.")
    probe = User(email=inv.email, first_name=inv.first_name, last_name=inv.last_name)
    validate_password(password, probe)  # raises django ValidationError

    user = User.objects.create_user(email=inv.email, password=password, first_name=inv.first_name,
                                    last_name=inv.last_name, phone=inv.phone, role=inv.role)
    if inv.kind == Invitation.Kind.STAFF:
        StaffProfile.objects.create(user=user, job_title=inv.job_title)
        from properties.models import Property

        for prop in Property.objects.filter(pk__in=inv.property_ids or []):
            PropertyAssignment.objects.get_or_create(user=user, property=prop,
                                                     defaults={"assigned_by": inv.created_by})
    else:
        tenant.user = user
        tenant.save(update_fields=["user", "updated_at"])
    inv.accepted_at = timezone.now()
    inv.accepted_user = user
    inv.save(update_fields=["accepted_at", "accepted_user", "tenancy"])
    return user, inv


# ------------------------------------------------------------------ revoking access
def revoke_sessions(user):
    """Delete every server-side session belonging to the user (database
    session backend). Deactivated users are also rejected on each request by
    Django's ModelBackend, so this is defence in depth."""
    uid = str(user.pk)
    removed = 0
    for s in Session.objects.filter(expire_date__gt=timezone.now()).iterator():
        try:
            data = s.get_decoded()
        except Exception:  # noqa: BLE001 - corrupt session: ignore
            continue
        if data.get("_auth_user_id") == uid:
            s.delete()
            removed += 1
    return removed


def deactivate_account(user, by=None, reason=""):
    """Block sign-in, end all sessions and cancel open invitations. History
    (payments, ledgers, tenancies, audit log) is untouched."""
    if user.is_active:
        user.is_active = False
        user.save(update_fields=["is_active", "updated_at"])
    revoke_sessions(user)
    revoke_open_invitations(email=user.email, by=by, reason=reason or "Account deactivated")


def end_tenant_portal_access(tenant, by=None, reason="Tenancy ended"):
    revoke_open_invitations(tenant=tenant, by=by, reason=reason)
    if tenant.user_id:
        deactivate_account(tenant.user, by=by, reason=reason)


def admin_exists():
    from django.db.models import Q

    return User.objects.filter(Q(role=Role.ADMIN) | Q(is_superuser=True), is_active=True).exists()
