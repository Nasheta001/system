"""
Django settings for the property management platform.

All secrets and environment-specific values are read from environment
variables (optionally loaded from backend/.env). See .env.example.
"""
import os
import sys
import warnings
from datetime import timedelta
from pathlib import Path

import dj_database_url
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def env(name, default=None):
    return os.environ.get(name, default)


def env_bool(name, default=False):
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


def env_list(name, default=""):
    return [v.strip() for v in os.environ.get(name, default).split(",") if v.strip()]


TESTING = len(sys.argv) > 1 and sys.argv[1] == "test"
DEBUG = env_bool("DJANGO_DEBUG", False)

SECRET_KEY = env("DJANGO_SECRET_KEY")
if not SECRET_KEY:
    if DEBUG or TESTING:
        SECRET_KEY = "dev-only-insecure-key-change-me"
    else:
        raise RuntimeError("DJANGO_SECRET_KEY must be set when DEBUG is off.")

ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "django_filters",
    "corsheaders",
    "drf_spectacular",
    "accounts",
    "properties",
    "tenancies",
    "leasing",
    "billing",
    "communications",
    "documents",
    "maintenance",
    "reports",
]

MIDDLEWARE = [
    # Answers load-balancer health checks before host/HTTPS checks (ALB probes use
    # the task IP as Host and plain HTTP).
    "config.middleware.HealthCheckMiddleware",
    "config.middleware.OriginVerifyMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "config.middleware.SecurityHeadersMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# --- Database -------------------------------------------------------------
# PostgreSQL is the supported database. Set DATABASE_URL, e.g.
#   postgres://propman:password@localhost:5432/propman
# If DATABASE_URL is not set, a local SQLite file is used so the project can
# still start; this fallback is for quick local trials only.
DATABASE_URL = env("DATABASE_URL")
if not DATABASE_URL and env("DB_HOST"):
    # On AWS the password comes from the RDS-managed secret as a separate value.
    from urllib.parse import quote

    DATABASE_URL = "postgres://{}:{}@{}:{}/{}".format(
        quote(env("DB_USER", "propman"), safe=""), quote(env("DB_PASSWORD", ""), safe=""),
        env("DB_HOST"), env("DB_PORT", "5432"), env("DB_NAME", "propman"),
    )
if DATABASE_URL:
    DATABASES = {
        "default": dj_database_url.parse(
            DATABASE_URL, conn_max_age=int(env("DB_CONN_MAX_AGE", "60")), conn_health_checks=True,
            ssl_require=env_bool("DB_SSL_REQUIRE", False),
        )
    }
else:
    if not TESTING:
        warnings.warn(
            "DATABASE_URL is not set: using SQLite fallback (db.sqlite3). "
            "Configure PostgreSQL for real use.",
            stacklevel=1,
        )
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }

AUTH_USER_MODEL = "accounts.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 10}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-gb"
TIME_ZONE = env("TIME_ZONE", "Africa/Nairobi")
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

# --- File storage -----------------------------------------------------------
# Public media (property photos) is served from MEDIA_URL.
# Private files (documents, receipts, attachments) live under PRIVATE_MEDIA_ROOT
# and are only ever streamed through permission-checked API endpoints.
MEDIA_URL = "/media/"
MEDIA_ROOT = Path(env("MEDIA_ROOT", BASE_DIR / "media"))
PRIVATE_MEDIA_ROOT = Path(env("PRIVATE_MEDIA_ROOT", BASE_DIR / "private_media"))

# STORAGE_BACKEND=local (default) or s3. With s3, public photos go to
# AWS_STORAGE_BUCKET_NAME (served through CloudFront at /media/) and private
# files to AWS_PRIVATE_BUCKET_NAME (never public; streamed by Django after
# permission checks). Credentials come from the ECS task IAM role – never set
# access keys in production.
STORAGE_BACKEND = env("STORAGE_BACKEND", "local")
if STORAGE_BACKEND == "s3":
    AWS_S3_REGION_NAME = env("AWS_S3_REGION_NAME", "af-south-1")
    AWS_STORAGE_BUCKET_NAME = env("AWS_STORAGE_BUCKET_NAME")
    AWS_PRIVATE_BUCKET_NAME = env("AWS_PRIVATE_BUCKET_NAME")
    if not (AWS_STORAGE_BUCKET_NAME and AWS_PRIVATE_BUCKET_NAME):
        raise RuntimeError("STORAGE_BACKEND=s3 requires AWS_STORAGE_BUCKET_NAME and AWS_PRIVATE_BUCKET_NAME.")
    AWS_S3_CUSTOM_DOMAIN = env("AWS_S3_CUSTOM_DOMAIN", "")  # e.g. www.example.co.ke (CloudFront)
    # S3-compatible providers (e.g. Supabase Storage): set the endpoint and use path-style
    # addressing. Access keys are then read from AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY.
    AWS_S3_ENDPOINT_URL = env("AWS_S3_ENDPOINT_URL", "") or None
    AWS_S3_ADDRESSING_STYLE = env("AWS_S3_ADDRESSING_STYLE", "path" if AWS_S3_ENDPOINT_URL else "auto")
    AWS_S3_SIGNATURE_VERSION = "s3v4"
    AWS_DEFAULT_ACL = None
    AWS_S3_FILE_OVERWRITE = False
    # AES256 server-side encryption is an AWS feature; disable it for providers that reject the header.
    AWS_S3_OBJECT_PARAMETERS = ({"ServerSideEncryption": "AES256"}
                                if env_bool("AWS_S3_SERVER_SIDE_ENCRYPTION", not AWS_S3_ENDPOINT_URL) else {})
    STORAGES = {
        "default": {
            "BACKEND": "storages.backends.s3.S3Storage",
            "OPTIONS": {"bucket_name": AWS_STORAGE_BUCKET_NAME, "location": "media", "querystring_auth": False,
                        "custom_domain": AWS_S3_CUSTOM_DOMAIN or None},
        },
        "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
    }
else:
    STORAGES = {
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage" if DEBUG or TESTING
            else "whitenoise.storage.CompressedManifestStaticFilesStorage"
        },
    }
DATA_UPLOAD_MAX_NUMBER_FILES = 10
DATA_UPLOAD_MAX_NUMBER_FIELDS = 500
MAX_UPLOAD_MB = int(env("MAX_UPLOAD_MB", "10"))
DATA_UPLOAD_MAX_MEMORY_SIZE = MAX_UPLOAD_MB * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- Sessions, CSRF and cookies ---------------------------------------------
# The Angular app uses cookie sessions + CSRF. Angular's HttpClient reads the
# XSRF-TOKEN cookie and sends it back in the X-XSRF-TOKEN header.
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_AGE = int(env("SESSION_COOKIE_AGE", str(60 * 60 * 24 * 14)))
CSRF_COOKIE_NAME = "XSRF-TOKEN"
CSRF_HEADER_NAME = "HTTP_X_XSRF_TOKEN"
CSRF_COOKIE_HTTPONLY = False  # Angular must be able to read it
CSRF_COOKIE_SAMESITE = "Lax"
# "__Host-" cookies are only accepted over HTTPS, for the exact host, path "/".
SESSION_COOKIE_NAME = "__Host-sessionid" if env_bool("SECURE_HTTPS", not DEBUG and not TESTING) else "sessionid"
CSRF_TRUSTED_ORIGINS = env_list("CSRF_TRUSTED_ORIGINS", "http://localhost:4200,http://127.0.0.1:4200")

CORS_ALLOWED_ORIGINS = env_list("CORS_ALLOWED_ORIGINS", "")
CORS_ALLOW_CREDENTIALS = True

SECURE_HTTPS = env_bool("SECURE_HTTPS", not DEBUG and not TESTING)
if SECURE_HTTPS:
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_SSL_REDIRECT = env_bool("SECURE_SSL_REDIRECT", True)
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_HSTS_SECONDS = int(env("SECURE_HSTS_SECONDS", "31536000"))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = env_bool("SECURE_HSTS_PRELOAD", False)
    # Health checks from the load balancer arrive over plain HTTP.
    SECURE_REDIRECT_EXEMPT = [r"^api/health/"]
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"
SECURE_REFERRER_POLICY = "same-origin"

# Number of trusted reverse proxies in front of Django that append to
# X-Forwarded-For (CloudFront + ALB = 2). Used to find the real client IP for
# rate limiting, audit logs and the M-Pesa IP allow-list. 0 = use REMOTE_ADDR.
NUM_PROXIES = int(env("NUM_PROXIES", "0"))

# If set, every request (except health checks) must carry the header
# X-Origin-Verify with this value. CloudFront adds it as a custom origin
# header, so the ALB cannot be used directly to bypass CloudFront/WAF.
ORIGIN_VERIFY_SECRET = env("ORIGIN_VERIFY_SECRET", "")

# Field-level encryption for especially sensitive personal data (e.g. national
# ID numbers). Comma-separated Fernet keys; the first encrypts, all decrypt
# (supports rotation). Generate one with:
#   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
FIELD_ENCRYPTION_KEYS = env_list("FIELD_ENCRYPTION_KEYS", "")
if not FIELD_ENCRYPTION_KEYS and not (DEBUG or TESTING):
    raise RuntimeError("FIELD_ENCRYPTION_KEYS must be set when DEBUG is off.")
if FIELD_ENCRYPTION_KEYS and not (DEBUG or TESTING) and "collectstatic" not in sys.argv:
    from cryptography.fernet import Fernet

    try:
        [Fernet(k.encode()) for k in FIELD_ENCRYPTION_KEYS]
    except (ValueError, TypeError) as _exc:
        raise RuntimeError("FIELD_ENCRYPTION_KEYS contains an invalid Fernet key.") from _exc

# Optional Cloudflare Turnstile bot protection on public forms and password
# reset. Inactive when the secret key is empty (honeypot checks always apply).
TURNSTILE_SITE_KEY = env("TURNSTILE_SITE_KEY", "")
TURNSTILE_SECRET_KEY = env("TURNSTILE_SECRET_KEY", "")

# Account lock-out on repeated failed logins (per email address).
LOGIN_MAX_FAILURES = int(env("LOGIN_MAX_FAILURES", "5"))
LOGIN_LOCKOUT_MINUTES = int(env("LOGIN_LOCKOUT_MINUTES", "15"))

# Invitation-only accounts. Links expire after this many hours and work once.
INVITATION_TTL_HOURS = int(env("INVITATION_TTL_HOURS", "72"))
# One-time "create the first administrator" page. Only works while no
# administrator exists. With DEBUG off it additionally requires this token;
# leave it empty to disable the page and use `manage.py createsuperuser`.
SETUP_TOKEN = env("SETUP_TOKEN", "")

# --- REST framework ------------------------------------------------------------
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ["accounts.authentication.CsrfSessionAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_FILTER_BACKENDS": [
        "django_filters.rest_framework.DjangoFilterBackend",
        "rest_framework.filters.SearchFilter",
        "rest_framework.filters.OrderingFilter",
    ],
    "DEFAULT_PAGINATION_CLASS": "config.pagination.StandardPagination",
    "PAGE_SIZE": 25,
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "anon": env("THROTTLE_ANON", "120/min"),
        "user": env("THROTTLE_USER", "600/min"),
        "login": env("THROTTLE_LOGIN", "10/min"),
        "password_reset": env("THROTTLE_PASSWORD_RESET", "5/hour"),
        "public_forms": env("THROTTLE_PUBLIC_FORMS", "20/hour"),
        "payments": env("THROTTLE_PAYMENTS", "10/min"),
        "invitation": env("THROTTLE_INVITATION", "20/hour"),
        "setup": env("THROTTLE_SETUP", "5/hour"),
    },
    "EXCEPTION_HANDLER": "config.exceptions.safe_exception_handler",
    "NUM_PROXIES": NUM_PROXIES or None,
    # JSON only in production: no browsable API pages.
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"] + (
        ["rest_framework.renderers.BrowsableAPIRenderer"] if DEBUG else []
    ),
}

SPECTACULAR_SETTINGS = {
    "TITLE": "Property Management Platform API",
    "DESCRIPTION": "REST API for the public website, management dashboard and tenant portal.",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "SERVE_PERMISSIONS": ["rest_framework.permissions.IsAdminUser"] if not DEBUG else [],
}

# Rate limits, login lock-outs and the worker heartbeat live in the cache. With
# several containers the cache must be shared: CACHE_BACKEND=db uses a
# PostgreSQL table (run "python manage.py createcachetable"); no Redis needed.
if env("CACHE_BACKEND", "locmem") == "db":
    CACHES = {"default": {"BACKEND": "django.core.cache.backends.db.DatabaseCache", "LOCATION": "django_cache"}}
else:
    CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}

# --- Email -----------------------------------------------------------------------
EMAIL_BACKEND = env("EMAIL_BACKEND", "django.core.mail.backends.console.EmailBackend")
EMAIL_HOST = env("EMAIL_HOST", "")
EMAIL_PORT = int(env("EMAIL_PORT", "587"))
EMAIL_HOST_USER = env("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", True)
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", "no-reply@example.co.ke")

# Public URL of the Angular app, used in emails / SMS links.
FRONTEND_URL = env("FRONTEND_URL", "http://localhost:4200").rstrip("/")

# --- Notification providers -----------------------------------------------------
# Channels are only "live" when explicitly enabled AND configured. Otherwise
# messages are written to the notification log with status "logged" and are
# never reported as delivered externally.
NOTIFICATIONS = {
    "EMAIL_ENABLED": env_bool("NOTIFY_EMAIL_ENABLED", False),
    "SMS_PROVIDER": env("SMS_PROVIDER", "log"),  # log | africastalking
    "AFRICASTALKING_USERNAME": env("AFRICASTALKING_USERNAME", ""),
    "AFRICASTALKING_API_KEY": env("AFRICASTALKING_API_KEY", ""),
    "AFRICASTALKING_SENDER_ID": env("AFRICASTALKING_SENDER_ID", ""),
    "AFRICASTALKING_SANDBOX": env_bool("AFRICASTALKING_SANDBOX", True),
    "WHATSAPP_PROVIDER": env("WHATSAPP_PROVIDER", "log"),  # log | meta
    "WHATSAPP_TOKEN": env("WHATSAPP_TOKEN", ""),
    "WHATSAPP_PHONE_NUMBER_ID": env("WHATSAPP_PHONE_NUMBER_ID", ""),
    "MAX_ATTEMPTS": int(env("NOTIFY_MAX_ATTEMPTS", "4")),
}

# --- M-Pesa Daraja ----------------------------------------------------------------
# MPESA_MODE: disabled | simulated | sandbox | production
MPESA = {
    "MODE": env("MPESA_MODE", "simulated"),
    "CONSUMER_KEY": env("MPESA_CONSUMER_KEY", ""),
    "CONSUMER_SECRET": env("MPESA_CONSUMER_SECRET", ""),
    "SHORTCODE": env("MPESA_SHORTCODE", "174379"),
    "PASSKEY": env("MPESA_PASSKEY", ""),
    "TRANSACTION_TYPE": env("MPESA_TRANSACTION_TYPE", "CustomerPayBillOnline"),
    "CALLBACK_BASE_URL": env("MPESA_CALLBACK_BASE_URL", "").rstrip("/"),
    "CALLBACK_TOKEN": env("MPESA_CALLBACK_TOKEN", "dev-callback-token"),
    "ALLOWED_CALLBACK_IPS": env_list("MPESA_ALLOWED_CALLBACK_IPS", ""),
    "TIMEOUT_MINUTES": int(env("MPESA_TIMEOUT_MINUTES", "10")),
}

# LOG_FORMAT=json emits one JSON object per line (CloudWatch Logs Insights friendly).
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "simple": {"format": "[{asctime}] {levelname} {name}: {message}", "style": "{"},
        "json": {"()": "config.logging.JsonFormatter"},
    },
    "handlers": {"console": {"class": "logging.StreamHandler",
                             "formatter": "json" if env("LOG_FORMAT", "text") == "json" else "simple"}},
    "root": {"handlers": ["console"], "level": env("LOG_LEVEL", "INFO")},
    "loggers": {"django.db.backends": {"level": "WARNING"}},
}

if TESTING:
    PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
    MEDIA_ROOT = Path(env("TEST_MEDIA_ROOT", BASE_DIR / "test_media"))
    PRIVATE_MEDIA_ROOT = Path(env("TEST_PRIVATE_MEDIA_ROOT", BASE_DIR / "test_private_media"))
    EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    NOTIFICATIONS["EMAIL_ENABLED"] = False  # tests never depend on a developer's local email setup
    REST_FRAMEWORK["DEFAULT_THROTTLE_CLASSES"] = []
    MPESA["MODE"] = "simulated"
    LOGGING["root"]["level"] = "ERROR"
    FIELD_ENCRYPTION_KEYS = ["MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY="]  # test-only key
