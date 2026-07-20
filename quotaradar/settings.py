"""Django settings for the QuotaRadar application."""

from __future__ import annotations

import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

from apps.monitoring.schedules import DatabasePollingSchedule

from .database import DatabaseUrlError, parse_database_url

BASE_DIR = Path(__file__).resolve().parent.parent


def required_environment(name: str) -> str:
    value = os.environ.get(name)
    if value is None or not value.strip():
        raise ImproperlyConfigured(f"Required environment variable {name} is not set.")
    return value.strip()


SECRET_KEY = required_environment("DJANGO_SECRET_KEY")
DEBUG = False
ALLOWED_HOSTS = ["localhost", "127.0.0.1", "[::1]", "web"]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
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
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "quotaradar.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
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
    DATABASES = {"default": parse_database_url(required_environment("DATABASE_URL"))}
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

CELERY_BEAT_MAX_LOOP_INTERVAL = 5.0
CELERY_BEAT_SCHEDULE: dict[str, object] = {
    "poll-sources": {
        "task": "monitoring.poll_sources",
        "schedule": DatabasePollingSchedule(),
    }
}

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "default": {
            "()": "apps.secrets.redaction.SafeFormatter",
            "format": "%(asctime)s %(levelname)s %(name)s %(message)s",
        }
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "default",
        }
    },
    "root": {
        "handlers": ["console"],
        "level": "INFO",
    },
}
