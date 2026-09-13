"""Build the admin health panel: every subsystem checked, worst verdict on top."""
from __future__ import annotations

import logging

from django.utils import timezone

from apps.configuration.models import SystemConfiguration
from apps.news.models import NewsConfiguration

from .errors import recent_errors
from .news import check_news_collection, check_news_editorial, check_news_publishing
from .quota import check_ai_analysis, check_telegram_quota, check_x_polling
from .report import ERROR, Check, Dashboard, clock, headline_for, worst
from .workers import check_scheduler, check_workers

logger = logging.getLogger(__name__)


def build_dashboard() -> Dashboard:
    now = timezone.now()
    config = SystemConfiguration.load()
    news_config = NewsConfiguration.load()
    checks = [
        _guard(check_workers),
        _guard(check_scheduler, config, news_config, now),
        _guard(check_x_polling, config, now),
        _guard(check_ai_analysis, config, now),
        _guard(check_telegram_quota, config, now),
        _guard(check_news_collection, news_config, now),
        _guard(check_news_editorial, news_config, now),
        _guard(check_news_publishing, news_config, now),
    ]
    try:
        errors = recent_errors(now)
    except Exception:  # The error feed is secondary; the cards must still render.
        logger.exception("Health panel: recent errors could not be loaded.")
        errors = []
    return Dashboard(generated_at=clock(now, config.telegram_message_timezone), level=worst(checks),
                     headline=headline_for(checks), checks=checks, errors=errors)


def _guard(check, *args) -> Check:
    """A broken check reports itself as an error instead of taking the admin index down."""
    name = getattr(check, "__name__", "check")
    try:
        return check(*args)
    except Exception as exc:
        logger.exception("Health panel check failed: %s", name)
        broken = Check(name.replace("check_", "").replace("_", " "))
        broken.fail(ERROR, f"Проверка упала: {type(exc).__name__}: {exc}")
        return broken
