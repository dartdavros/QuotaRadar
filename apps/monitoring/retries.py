"""Retry policy for temporary X API failures."""

from __future__ import annotations

import logging

from celery import Task

from apps.sources.models import Source

from .events import record_monitoring_event
from .models import MonitoringComponent, MonitoringEventStatus

logger = logging.getLogger(__name__)
_BASE_RETRY_SECONDS = 30
_MAX_RETRY_SECONDS = 900


def retry_countdown(task: Task) -> int:
    retries = getattr(task.request, "retries", 0)
    return min(_BASE_RETRY_SECONDS * (2**retries), _MAX_RETRY_SECONDS)


def retry_x_task(
    task: Task,
    exc: Exception,
    retry_count: int,
    countdown: int,
    *,
    sources: list[Source],
) -> None:
    task_id = str(getattr(task.request, "id", "") or "")
    for source in sources:
        record_monitoring_event(
            component=MonitoringComponent.X,
            status=MonitoringEventStatus.ERROR,
            source=source,
            message=f"{exc} Повтор через {countdown} сек.",
            error_type=type(exc).__name__,
            task_id=task_id,
        )
    logger.warning(
        "Temporary X API failure; retry scheduled.",
        extra={
            "event": "monitoring.x_retry_scheduled",
            "task_id": task_id,
            "status": "retry",
            "error_type": type(exc).__name__,
        },
    )
    raise task.retry(
        exc=exc,
        countdown=countdown,
        max_retries=retry_count,
    )
