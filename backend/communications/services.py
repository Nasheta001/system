import logging
import re
from datetime import timedelta

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from accounts.models import CompanySettings, Role, User

from .models import Announcement, AnnouncementRecipient, Notification, NotificationAttempt, NotificationTemplate
from .providers import ProviderError, get_provider

logger = logging.getLogger(__name__)

# Default wording. Editable in the dashboard (Settings → Message templates).
# SMS/WhatsApp texts are deliberately short and contain no private history.
DEFAULT_TEMPLATES = {
    "payment_received": (
        "Payment received",
        "Hello {first_name},\n\nWe have received your payment of KES {amount} for {property}. "
        "Receipt number: {receipt}. Your outstanding balance is now KES {balance}.{simulated_note}\n\n{company}",
        "{company}: Payment of KES {amount} received. Receipt {receipt}.{simulated_note} Details: {link}",
    ),
    "rent_upcoming": (
        "Upcoming rent payment",
        "Hello {first_name},\n\nThis is a friendly reminder that your rent of KES {amount} for {unit} "
        "is due on {due_date}.\n\nYou can pay securely from your tenant portal.\n\n{company}",
        "{company}: Friendly reminder – rent of KES {amount} is due on {due_date}. Pay: {link}",
    ),
    "rent_due": (
        "Rent due today",
        "Hello {first_name},\n\nYour rent payment of KES {amount} for {unit} is due today ({due_date}).\n\n{company}",
        "{company}: Your rent of KES {amount} is due today. Pay: {link}",
    ),
    "rent_overdue": (
        "Rent balance outstanding",
        "Hello {first_name},\n\nOur records show an outstanding balance of KES {amount} on your account for "
        "{unit}, due since {due_date}. If you have already paid, please ignore this message or contact the "
        "office so we can update your records.\n\n{company}",
        "{company}: A balance of KES {amount} remains on your rent account. Details: {link}",
    ),
    "announcement_new": (
        "New notice: {title}",
        "Hello {first_name},\n\nA new notice has been posted: {title}.\n\n{body}\n\n{company}",
        "{company}: New notice – {title}. Read: {link}",
    ),
    "document_action": (
        "Action required: {title}",
        "Hello {first_name},\n\nA document requires your {action}: {title}. Please open your tenant portal "
        "to review it.\n\n{company}",
        "{company}: Please review '{title}' ({action} needed): {link}",
    ),
    "application_status": (
        "Application {reference} update",
        "Hello {first_name},\n\nThe status of your rental application {reference} is now: {status}.\n"
        "{message}\n\n{company}",
        "{company}: Application {reference} is now {status}.",
    ),
    "maintenance_update": (
        "Maintenance request {reference} update",
        "Hello {first_name},\n\nYour maintenance request {reference} ({title}) is now: {status}.\n{message}\n\n{company}",
        "{company}: Maintenance request {reference} is now {status}. Details: {link}",
    ),
    "tenancy_change": (
        "Tenancy update",
        "Hello {first_name},\n\n{message}\n\n{company}",
        "{company}: {message}",
    ),
    "account_invite": (
        "Your account at {company}",
        "Hello {first_name},\n\nAn account has been created for you. Set your password using this secure link "
        "(valid for 3 days):\n{reset_link}\n\n{company}",
        "{company}: Your portal account is ready. Check your email to set a password.",
    ),
    "staff_invite": (
        "You are invited to {company}",
        "Hello {first_name},\n\nYou have been invited to join {company} as {role}. Create your password using "
        "this secure, single-use link (valid for {valid_for}):\n{invite_link}\n\n"
        "If you were not expecting this invitation, ignore this email and no account will be created.\n\n{company}",
        "{company}: You have been invited to the management system. Check your email to accept.",
    ),
    "tenant_invite": (
        "Your tenant portal invitation",
        "Hello {first_name},\n\nYou can now use the {company} tenant portal to view your rent account, pay rent, "
        "read notices and report repairs. Activate your account with this secure, single-use link "
        "(valid for {valid_for}):\n{invite_link}\n\nIf you were not expecting this, ignore this email.\n\n{company}",
        "{company}: Your tenant portal invitation has been emailed to you. It is valid for {valid_for}.",
    ),
    "password_reset": (
        "Reset your password",
        "Hello {first_name},\n\nUse this secure link to reset your password (valid for 3 days):\n{reset_link}\n\n"
        "If you did not request this, you can ignore this email.\n\n{company}",
        "{company}: Check your email for a password reset link.",
    ),
    "staff_alert": (
        "Follow-up required: {title}",
        "{message}",
        "{company}: {title}",
    ),
}


_PLACEHOLDER = re.compile(r"\{([a-z_]{1,40})\}")
SECRET_LINK_TEMPLATES = {"password_reset", "account_invite", "staff_invite", "tenant_invite"}
_SECRET_LINK = re.compile(r"https?://\S*(?:reset-password|accept-invite)\S*")


def _fill(template, ctx):
    """Replace {name} placeholders only. Unlike str.format this never evaluates
    attribute or index expressions, so staff-edited templates cannot read
    internal objects."""
    return _PLACEHOLDER.sub(lambda m: str(ctx.get(m.group(1), "")), template)


def redact_secret_links(text):
    return _SECRET_LINK.sub("[secure link hidden]", text or "")


def ensure_templates():
    for key, (subject, body, short) in DEFAULT_TEMPLATES.items():
        NotificationTemplate.objects.get_or_create(
            key=key, defaults={"name": key.replace("_", " ").capitalize(), "subject": subject, "body": body,
                               "short_body": short},
        )


def render(template_key, context):
    tpl = NotificationTemplate.objects.filter(key=template_key, is_active=True).first()
    if tpl:
        subject, body, short = tpl.subject, tpl.body, tpl.short_body
    else:
        subject, body, short = DEFAULT_TEMPLATES.get(template_key, ("{title}", "{message}", "{message}"))
    ctx = dict(context)
    ctx.setdefault("company", CompanySettings.load().name)
    return _fill(subject, ctx)[:200], _fill(body, ctx), _fill(short, ctx)[:320]


def _create_notification(**kwargs):
    dedupe = kwargs.get("dedupe_key")
    if dedupe and Notification.objects.filter(dedupe_key=dedupe).exists():
        return None
    try:
        with transaction.atomic():
            return Notification.objects.create(**kwargs)
    except IntegrityError:
        return None


def _queue(notifications):
    ids = [n.pk for n in notifications if n is not None]
    if ids:
        transaction.on_commit(lambda: deliver_many(ids))
    return [n for n in notifications if n is not None]


def notify_tenant(tenant, template_key, context, link="", channels=None, dedupe=None, related=None):
    """Create notifications for a tenant on their preferred channels."""
    if channels is None:
        channels = ["in_app", "email", "sms"]
    ctx = {"first_name": tenant.first_name, **context}
    ctx["link"] = f"{settings.FRONTEND_URL}{link}" if link else settings.FRONTEND_URL
    subject, body, short = render(template_key, ctx)
    rel_type, rel_id = related or ("", "")
    out = []
    for channel in channels:
        to, text = "", body
        if channel == "in_app":
            if not tenant.user_id:
                continue
        elif channel == "email":
            if not (tenant.notify_email and tenant.email):
                continue
            to = tenant.email
        elif channel == "sms":
            if not (tenant.notify_sms and tenant.phone):
                continue
            to, text = tenant.phone, short
        elif channel == "whatsapp":
            if not (tenant.notify_whatsapp and tenant.phone):
                continue
            to, text = tenant.phone, short
        out.append(_create_notification(
            user_id=tenant.user_id, tenant=tenant, channel=channel, to_address=to, template_key=template_key,
            subject=subject, body=text, link=link, dedupe_key=f"{dedupe}:{channel}" if dedupe else None,
            related_type=rel_type, related_id=str(rel_id),
        ))
    return _queue(out)


def notify_user(user, template_key, context, link="", channels=("in_app", "email"), dedupe=None, related=None):
    """Notify a staff (or any) user account."""
    ctx = {"first_name": user.first_name or "there", **context}
    ctx["link"] = f"{settings.FRONTEND_URL}{link}" if link else settings.FRONTEND_URL
    subject, body, short = render(template_key, ctx)
    rel_type, rel_id = related or ("", "")
    out = []
    for channel in channels:
        to = user.email if channel == "email" else (user.phone if channel in ("sms", "whatsapp") else "")
        if channel != "in_app" and not to:
            continue
        out.append(_create_notification(
            user=user, channel=channel, to_address=to, template_key=template_key, subject=subject,
            body=short if channel in ("sms", "whatsapp") else body, link=link,
            dedupe_key=f"{dedupe}:{channel}" if dedupe else None, related_type=rel_type, related_id=str(rel_id),
        ))
    return _queue(out)


def notify_address(channel, to_address, template_key, context, dedupe=None, related=None):
    """Notify someone without an account (e.g. a rental applicant)."""
    subject, body, short = render(template_key, context)
    rel_type, rel_id = related or ("", "")
    n = _create_notification(
        channel=channel, to_address=to_address, template_key=template_key, subject=subject,
        body=short if channel in ("sms", "whatsapp") else body,
        dedupe_key=f"{dedupe}:{channel}" if dedupe else None, related_type=rel_type, related_id=str(rel_id),
    )
    return _queue([n])


def deliver(notification):
    if notification.status not in (Notification.Status.QUEUED, Notification.Status.FAILED):
        return notification
    provider = get_provider(notification.channel)
    notification.attempts += 1
    try:
        result = provider.send(notification)
    except ProviderError as exc:
        max_attempts = settings.NOTIFICATIONS["MAX_ATTEMPTS"]
        notification.last_error = str(exc)[:500]
        notification.status = Notification.Status.FAILED
        if notification.attempts < max_attempts:
            # Exponential back-off: 2, 4, 8 ... minutes
            notification.next_attempt_at = timezone.now() + timedelta(minutes=2 ** notification.attempts)
        else:
            notification.next_attempt_at = timezone.now() + timedelta(days=3650)
        notification.save(update_fields=["attempts", "last_error", "status", "next_attempt_at"])
        NotificationAttempt.objects.create(
            notification=notification, provider=getattr(provider, "name", "?"), success=False, error=str(exc)[:500]
        )
        return notification
    notification.status = result.status
    notification.sent_at = timezone.now()
    notification.last_error = ""
    if result.status == "sent" and notification.template_key in SECRET_LINK_TEMPLATES:
        # Once handed to the provider, the stored copy no longer needs the secret link.
        notification.body = redact_secret_links(notification.body)
    notification.save(update_fields=["attempts", "status", "sent_at", "last_error", "body"])
    NotificationAttempt.objects.create(
        notification=notification, provider=result.provider, success=True, provider_message_id=result.message_id
    )
    return notification


def deliver_many(ids):
    for n in Notification.objects.filter(pk__in=ids, status=Notification.Status.QUEUED):
        try:
            deliver(n)
        except Exception:  # noqa: BLE001 - never break the calling request
            logger.exception("Notification delivery crashed for %s", n.pk)


def retry_failed(limit=200):
    max_attempts = settings.NOTIFICATIONS["MAX_ATTEMPTS"]
    qs = Notification.objects.filter(
        Q(status=Notification.Status.QUEUED) | Q(status=Notification.Status.FAILED, attempts__lt=max_attempts),
        next_attempt_at__lte=timezone.now(),
    )[:limit]
    count = 0
    for n in qs:
        deliver(n)
        count += 1
    return count


# --------------------------------------------------------------------------- announcements
def resolve_announcement_audience(announcement):
    """Return (tenancies, staff_users). Tenancies are current tenancies only, so
    property-specific notices never reach unrelated or former tenants."""
    from tenancies.models import Tenancy

    current = Tenancy.objects.filter(status__in=Tenancy.CURRENT_STATUSES).select_related("tenant", "property")
    a = announcement.audience
    if a == Announcement.Audience.ALL_TENANTS:
        tenancies = current
    elif a == Announcement.Audience.PROPERTIES:
        tenancies = current.filter(property__in=announcement.properties.all())
    elif a == Announcement.Audience.BUILDINGS:
        tenancies = current.filter(unit__building__in=announcement.buildings.all())
    elif a == Announcement.Audience.TENANTS:
        tenancies = current.filter(tenant__in=announcement.tenants.all())
    else:
        tenancies = current.none()
    staff = User.objects.none()
    if a == Announcement.Audience.STAFF:
        staff = announcement.staff.filter(is_active=True).exclude(role=Role.TENANT)
    # One recipient per tenant even if they hold several tenancies
    seen, unique = set(), []
    for t in tenancies.order_by("tenant_id", "-start_date"):
        if t.tenant_id not in seen:
            seen.add(t.tenant_id)
            unique.append(t)
    return unique, list(staff)


def publish_announcement(announcement, user=None):
    with transaction.atomic():
        ann = Announcement.objects.select_for_update().get(pk=announcement.pk)
        if ann.status == Announcement.Status.PUBLISHED:
            return ann
        ann.status = Announcement.Status.PUBLISHED
        ann.published_at = timezone.now()
        ann.save(update_fields=["status", "published_at", "updated_at"])
        tenancies, staff = resolve_announcement_audience(ann)
        channels = ["in_app"]
        if ann.send_email:
            channels.append("email")
        if ann.send_sms:
            channels.append("sms")
        if ann.send_whatsapp:
            channels.append("whatsapp")
        for t in tenancies:
            rec, created = AnnouncementRecipient.objects.get_or_create(
                announcement=ann, tenant=t.tenant, defaults={"user_id": t.tenant.user_id, "property": t.property}
            )
            if created:
                notify_tenant(
                    t.tenant, "announcement_new",
                    {"title": ann.title, "body": ann.body[:1500]},
                    link="/tenant/announcements", channels=channels,
                    dedupe=f"ann:{ann.pk}:t{t.tenant_id}", related=("Announcement", ann.pk),
                )
        for u in staff:
            _, created = AnnouncementRecipient.objects.get_or_create(announcement=ann, user=u, tenant=None)
            if created:
                notify_user(
                    u, "announcement_new", {"title": ann.title, "body": ann.body[:1500]},
                    link="/management/announcements", channels=[c for c in channels if c != "whatsapp"],
                    dedupe=f"ann:{ann.pk}:u{u.pk}", related=("Announcement", ann.pk),
                )
    return ann


def publish_scheduled_announcements(now=None):
    now = now or timezone.now()
    count = 0
    for ann in Announcement.objects.filter(status=Announcement.Status.SCHEDULED, publish_at__lte=now):
        publish_announcement(ann)
        count += 1
    return count
