from django.conf import settings
from django.contrib.auth.tokens import default_token_generator
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode


def password_reset_link(user):
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = default_token_generator.make_token(user)
    return f"{settings.FRONTEND_URL}/account/reset-password?uid={uid}&token={token}"


def send_password_link(user, template_key="password_reset"):
    """Email a single-use password set/reset link. When email delivery is not
    configured the message is stored in the notification log (status 'logged')
    so an administrator can see it during development."""
    from communications.services import notify_user

    notify_user(
        user, template_key,
        {"reset_link": password_reset_link(user), "first_name": user.first_name or "there"},
        channels=("email",),
    )
