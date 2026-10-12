"""Application-level encryption for especially sensitive columns.

Values are encrypted with Fernet (AES-128-CBC + HMAC-SHA256) before they reach
the database, so database dumps, snapshots and DB administrators never see the
plaintext. Keys come from FIELD_ENCRYPTION_KEYS (store them in AWS Secrets
Manager). Encrypted columns cannot be searched or filtered by value.
"""
import base64
import hashlib
import logging
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from django.conf import settings
from django.db import models

PREFIX = "enc1:"
logger = logging.getLogger(__name__)


@lru_cache(maxsize=4)
def _cipher(keys: tuple) -> MultiFernet:
    if not keys:
        # Development only (settings refuse to start without keys when DEBUG is off)
        derived = base64.urlsafe_b64encode(hashlib.sha256(settings.SECRET_KEY.encode()).digest())
        keys = (derived.decode(),)
    return MultiFernet([Fernet(k.encode() if isinstance(k, str) else k) for k in keys])


def cipher() -> MultiFernet:
    return _cipher(tuple(settings.FIELD_ENCRYPTION_KEYS))


def encrypt(value: str) -> str:
    if value in (None, "") or value.startswith(PREFIX):
        return value
    return PREFIX + cipher().encrypt(value.encode()).decode()


def decrypt(value):
    if not isinstance(value, str) or not value.startswith(PREFIX):
        return value  # empty, or legacy plaintext awaiting re-encryption
    try:
        return cipher().decrypt(value[len(PREFIX):].encode()).decode()
    except InvalidToken:
        # Fail loudly: a wrong/missing key must never silently corrupt data.
        logger.error("Could not decrypt an encrypted field – check FIELD_ENCRYPTION_KEYS")
        raise


class EncryptedTextField(models.TextField):
    description = "Text encrypted at the application layer"

    def from_db_value(self, value, expression, connection):
        return decrypt(value)

    def to_python(self, value):
        return decrypt(value)

    def get_prep_value(self, value):
        value = super().get_prep_value(value)
        return encrypt(value) if isinstance(value, str) else value
