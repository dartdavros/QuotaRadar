"""Django settings for the QuotaRadar application."""

from __future__ import annotations

import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

from apps.monitoring.schedules import DatabasePollingSchedule

from .database import DatabaseUrlError, database_config_from_environment

BASE_DIR = Path(__file__).resolve().parent.parent


def required_environment(name: str) -> str:
    value = os.environ.get(name)
    if value is None or not value.strip():
        raise ImproperlyConfigured(f"Required environment variable {name} is not set.")
    return value.strip()


def comma_separated_environment(name: str) -> list[str]:
    values = [value.strip() for value in required_environment(name).split(",")]
    result = [value for value in values if value]
    if not result:
        raise ImproperlyConfigured(
            f"Required environment variable {name} contains no values."
        )
    return result


SECRET_KEY = required_environment("DJANGO_SECRET_KEY")
DEBUG = False
ALLOWED_HOSTS = comma_separated_environment("DJANGO_ALLOWED_HOSTS")
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True

LOGIN_URL = "two_factor:login"
LOGIN_REDIRECT_URL = "/admin/"
OTP_TOTP_ISSUER = "QuotaRadar"

INSTALLED_APPS = [
    "quotaradar.apps.QuotaRadarAdminConfig",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django_otp",
    "django_otp.plugins.otp_totp",
    "django_otp.plugins.otp_static",
    "two_factor",
    "formtools",
    "apps.configuration.apps.ConfigurationConfig",
    "apps.secrets.apps.SecretsConfig",
    "apps.sources.apps.SourcesConfig",
    "apps.monitoring.apps.MonitoringConfig",
    "apps.analysis.apps.AnalysisConfig",
    "apps.telegram.apps.TelegramConfig",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django_otp.middleware.OTPMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "quotaradar.urls"

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

WSGI_APPLICATION = "quotaradar.wsgi.application"
ASGI_APPLICATION = "quotaradar.asgi.application"

try:
    DATABASES = {"default": database_config_from_environment(os.environ)}
except DatabaseUrlError as exc:
    raise ImproperlyConfigured(str(exc)) from exc

REDIS_URL = required_environment("REDIS_URL")
QUOTARADAR_MASTER_KEY_FILE = Path(required_environment("QUOTARADAR_MASTER_KEY_FILE"))

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"
    },
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "ru-ru"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

CELERY_BROKER_URL = REDIS_URL
CELERY_RESULT_BACKEND = REDIS_URL
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TIMEZONE = TIME_ZONE
CELERY_ENABLE_UTC = True
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True
CELERY_WORKER_HIJACK_ROOT_LOGGER = False
CELERY_TASK_ACKS_LATE = True
CELERY_TASK_REJECT_ON_WORKER_LOST = True
CELERY_TASK_TRACK_STARTED = True
CELERY_BROKER_TRANSPORT_OPTIONS = {"visibility_timeout": 3600}

QUOTARADAR_ANALYSIS_STALE_SECONDS = 1800
QUOTARADAR_DELIVERY_STALE_SECONDS = 1200
QUOTARADAR_RECOVERY_INTERVAL_SECONDS = 300

CELERY_BEAT_MAX_LOOP_INTERVAL = 5.0
CELERY_BEAT_SCHEDULE: dict[str, object] = {
    "poll-sources": {
        "task": "monitoring.poll_sources",
        "schedule": DatabasePollingSchedule(),
    },
    "recover-orphaned-work": {
        "task": "monitoring.recover_orphaned_work",
        "schedule": float(QUOTARADAR_RECOVERY_INTERVAL_SECONDS),
    },
}

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "json": {
            "()": "apps.configuration.logging.JsonLogFormatter",
        }
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "json",
        }
    },
    "root": {
        "handlers": ["console"],
        "level": "INFO",
    },
}
