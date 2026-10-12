"""Bot protection for public forms.

1. Honeypot: the Angular forms include a hidden "website" field that people
   never fill in. Any value means an automated submission.
2. Cloudflare Turnstile (optional): when TURNSTILE_SECRET_KEY is configured the
   request must carry a valid "captcha_token", verified server-side. If the
   verification service cannot be reached the request is rejected (fail closed).
Rate limits (DRF throttles + AWS WAF) apply in addition to these checks.
"""
import logging

import requests
from django.conf import settings
from rest_framework.exceptions import ValidationError

from accounts.audit import client_ip

logger = logging.getLogger(__name__)
HONEYPOT_FIELD = "website"
VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"


def check_human(request):
    data = request.data if hasattr(request, "data") else {}
    if str(data.get(HONEYPOT_FIELD, "") or "").strip():
        logger.info("Honeypot triggered from %s on %s", client_ip(request), request.path)
        raise ValidationError({"detail": "Your submission could not be processed."})
    secret = settings.TURNSTILE_SECRET_KEY
    if not secret:
        return
    token = str(data.get("captcha_token", "") or "")
    if not token:
        raise ValidationError({"detail": "Please complete the verification check."})
    try:
        resp = requests.post(VERIFY_URL, timeout=10, data={
            "secret": secret, "response": token, "remoteip": client_ip(request) or "",
        })
        ok = resp.json().get("success") is True
    except Exception:  # noqa: BLE001
        logger.warning("Turnstile verification unavailable")
        raise ValidationError({"detail": "Verification service unavailable. Please try again shortly."}) from None
    if not ok:
        raise ValidationError({"detail": "Verification failed. Please try again."})
