"""PostgreSQL and Redis settings for Docker/CI integration tests."""

from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# Prevent an unrelated host DATABASE_URL from overriding the Compose PostgreSQL settings.
os.environ.pop("DATABASE_URL", None)

os.environ.setdefault("DJANGO_SECRET_KEY", "integration-test-django-secret-key")
os.environ.setdefault("DJANGO_ALLOWED_HOSTS", "testserver,localhost,127.0.0.1")
os.environ.setdefault("REDIS_URL", "redis://redis:6379/15")
os.environ.setdefault(
    "QUOTARADAR_MASTER_KEY_FILE",
    str(BASE_DIR / "tests" / "fixtures" / "master.key"),
)

from . import settings as base_settings  # noqa: E402
from .settings import *  # noqa: F403,E402

PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True
STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
    },
}
MIDDLEWARE = [
    middleware
    for middleware in base_settings.MIDDLEWARE
    if middleware != "whitenoise.middleware.WhiteNoiseMiddleware"
]
