"""Delivery providers for each notification channel.

A provider returns a ProviderResult. When a channel is not configured the
"log" provider is used: the message is stored with status LOGGED and is never
reported as delivered externally.
"""
import logging
from dataclasses import dataclass

import requests
from django.conf import settings
from django.core.mail import send_mail

logger = logging.getLogger(__name__)


@dataclass
class ProviderResult:
    status: str  # sent | logged | delivered
    provider: str
    message_id: str = ""


class ProviderError(Exception):
    pass


class LogProvider:
    name = "log"

    def send(self, notification):
        logger.info(
            "[NOTIFICATION LOG – not delivered externally] %s to %s: %s",
            notification.channel, notification.to_address, notification.body[:200],
        )
        return ProviderResult(status="logged", provider=self.name)


class InAppProvider:
    name = "in_app"

    def send(self, notification):
        return ProviderResult(status="delivered", provider=self.name)


class EmailProvider:
    name = "email"

    def send(self, notification):
        body = notification.body
        if notification.link:
            body += f"\n\nOpen securely: {settings.FRONTEND_URL}{notification.link}"
        try:
            send_mail(notification.subject, body, settings.DEFAULT_FROM_EMAIL, [notification.to_address])
        except Exception as exc:  # noqa: BLE001
            raise ProviderError(str(exc)[:400]) from exc
        return ProviderResult(status="sent", provider=self.name)


class AfricasTalkingSMS:
    """Africa's Talking bulk SMS API. https://developers.africastalking.com/"""

    name = "africastalking"

    def __init__(self, cfg):
        self.cfg = cfg

    def send(self, notification):
        sandbox = self.cfg["AFRICASTALKING_SANDBOX"]
        url = (
            "https://api.sandbox.africastalking.com/version1/messaging"
            if sandbox else "https://api.africastalking.com/version1/messaging"
        )
        data = {"username": self.cfg["AFRICASTALKING_USERNAME"], "to": notification.to_address,
                "message": notification.body}
        if self.cfg["AFRICASTALKING_SENDER_ID"]:
            data["from"] = self.cfg["AFRICASTALKING_SENDER_ID"]
        try:
            resp = requests.post(
                url, data=data, timeout=20,
                headers={"apiKey": self.cfg["AFRICASTALKING_API_KEY"], "Accept": "application/json"},
            )
            resp.raise_for_status()
            recipients = resp.json().get("SMSMessageData", {}).get("Recipients", [])
        except Exception as exc:  # noqa: BLE001
            raise ProviderError(f"SMS provider error: {exc}"[:400]) from exc
        if not recipients or recipients[0].get("status") not in ("Success", "Sent"):
            raise ProviderError(f"SMS rejected: {recipients[:1]}")
        return ProviderResult(status="sent", provider=self.name, message_id=recipients[0].get("messageId", ""))


class MetaWhatsApp:
    """WhatsApp Cloud API text message. Note: business-initiated messages outside
    the 24h customer-service window require pre-approved templates."""

    name = "meta_whatsapp"

    def __init__(self, cfg):
        self.cfg = cfg

    def send(self, notification):
        url = f"https://graph.facebook.com/v20.0/{self.cfg['WHATSAPP_PHONE_NUMBER_ID']}/messages"
        payload = {
            "messaging_product": "whatsapp",
            "to": notification.to_address.lstrip("+"),
            "type": "text",
            "text": {"body": notification.body},
        }
        try:
            resp = requests.post(url, json=payload, timeout=20,
                                 headers={"Authorization": f"Bearer {self.cfg['WHATSAPP_TOKEN']}"})
            resp.raise_for_status()
            msg_id = resp.json().get("messages", [{}])[0].get("id", "")
        except Exception as exc:  # noqa: BLE001
            raise ProviderError(f"WhatsApp provider error: {exc}"[:400]) from exc
        return ProviderResult(status="sent", provider=self.name, message_id=msg_id)


def get_provider(channel):
    cfg = settings.NOTIFICATIONS
    if channel == "in_app":
        return InAppProvider()
    if channel == "email":
        return EmailProvider() if cfg["EMAIL_ENABLED"] else LogProvider()
    if channel == "sms":
        if cfg["SMS_PROVIDER"] == "africastalking" and cfg["AFRICASTALKING_API_KEY"]:
            return AfricasTalkingSMS(cfg)
        return LogProvider()
    if channel == "whatsapp":
        if cfg["WHATSAPP_PROVIDER"] == "meta" and cfg["WHATSAPP_TOKEN"]:
            return MetaWhatsApp(cfg)
        return LogProvider()
    return LogProvider()


def channel_status():
    """Human-readable status of each channel for the settings screen."""
    cfg = settings.NOTIFICATIONS
    return {
        "in_app": {"active": True, "detail": "Always on (tenant portal)"},
        "email": {
            "active": bool(cfg["EMAIL_ENABLED"]),
            "detail": f"SMTP via {settings.EMAIL_HOST}" if cfg["EMAIL_ENABLED"] else "Not enabled – messages are logged only",
        },
        "sms": {
            "active": isinstance(get_provider("sms"), AfricasTalkingSMS),
            "detail": (
                f"Africa's Talking ({'sandbox' if cfg['AFRICASTALKING_SANDBOX'] else 'live'})"
                if isinstance(get_provider("sms"), AfricasTalkingSMS) else "Not configured – messages are logged only"
            ),
        },
        "whatsapp": {
            "active": isinstance(get_provider("whatsapp"), MetaWhatsApp),
            "detail": "Meta WhatsApp Cloud API" if isinstance(get_provider("whatsapp"), MetaWhatsApp)
            else "Not configured – messages are logged only",
        },
    }
