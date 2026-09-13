"""Liveness of the Celery workers and the beat scheduler."""
from __future__ import annotations

from datetime import timedelta

from django.db.models import Max

from apps.sources.models import Source
from apps.sources.routing import quota_sources

from .report import ERROR, OFF, Check, admin_link, age, minutes

# Worker hostname prefixes started by docker/entrypoint.sh and the queues they serve.
EXPECTED_WORKERS = {"celery": "worker (лимиты)", "news-default": "news-worker", "news-urgent": "news-urgent"}
PING_TIMEOUT = 1.0
BEAT_GRACE = 3  # Missed poll intervals before the scheduler is declared dead.


def ping_workers() -> dict[str, str]:
    """Return {hostname: 'pong'} for live workers; raise if the broker is unreachable."""
    from quotaradar.celery import app

    replies = app.control.inspect(timeout=PING_TIMEOUT).ping() or {}
    return {host: "pong" for host in replies}


def check_workers() -> Check:
    check = Check("Воркеры Celery")
    try:
        alive = ping_workers()
    except Exception as exc:  # Broker down: every worker is effectively dead.
        check.fail(ERROR, f"Брокер Redis недоступен: {type(exc).__name__}: {exc}")
        return check
    missing = [label for prefix, label in EXPECTED_WORKERS.items()
               if not any(host.split("@", 1)[0] == prefix for host in alive)]
    if missing:
        check.fail(ERROR, f"Не отвечают: {', '.join(missing)}. Контейнер упал или не запущен.")
    check.details.append(f"Отвечают: {', '.join(sorted(alive)) or 'никто'}.")
    if not check.summary:
        check.summary = "Все воркеры отвечают."
    return check


def check_scheduler(config, news_config, now) -> Check:
    check = Check("Планировщик (beat)", links=[
        admin_link("События мониторинга", "monitoring_monitoringevent_changelist"),
    ])
    if not config.monitoring_enabled:
        if news_config.collection_enabled or news_config.analysis_enabled or news_config.publishing_enabled:
            check.summary = "Мониторинг лимитов выключен: живость beat видна только по новостям (см. карточки новостей)."
        else:
            check.fail(OFF, "Все потоки выключены: планировщику нечего запускать.")
        return check
    last = quota_sources(Source.objects.filter(enabled=True)).aggregate(m=Max("last_checked_at"))["m"]
    check.last_success = age(last, now)
    grace = config.poll_interval_seconds * BEAT_GRACE
    if last is None or last < now - timedelta(seconds=grace):
        check.fail(ERROR, f"Опрос источников не запускался дольше {minutes(grace)}: "
                          "контейнер beat или worker не работает.")
    else:
        check.summary = f"Задачи запускаются по расписанию (последний опрос {age(last, now)})."
    return check
