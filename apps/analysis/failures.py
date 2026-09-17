"""Retry, give-up and result shaping for one post analysis."""

from __future__ import annotations

import logging

from celery import Task

from apps.configuration.models import SystemConfiguration
from apps.monitoring.events import record_monitoring_event
from apps.monitoring.models import MonitoringComponent, MonitoringEventStatus
from apps.sources.models import SourcePost

from .models import Analysis
from .services import save_failed_analysis

logger = logging.getLogger(__name__)

BASE_RETRY_SECONDS = 30
MAX_RETRY_SECONDS = 900


def task_id(task: Task) -> str:
    return str(getattr(task.request, "id", "") or "")


def permanent_failure(
    *,
    task: Task,
    source_post: SourcePost,
    configuration: SystemConfiguration,
    exc: Exception,
    raw_response: object | None,
    context: dict[str, object],
) -> dict[str, int | str | bool]:
    """Store the error without retrying and report it to monitoring."""

    analysis = save_failed_analysis(
        source_post_id=source_post.pk,
        configuration=configuration,
        error=str(exc),
        raw_response=raw_response,
    )
    logger.error(
        "Post analysis failed permanently.",
        extra={
            **context,
            "event": "analysis.failed",
            "analysis_id": analysis.pk,
            "status": "failed",
            "error_type": type(exc).__name__,
        },
    )
    _record_failure_event(task=task, source_post=source_post, exc=exc)
    return failure_result(source_post_id=source_post.pk, analysis=analysis)


def retry_or_fail(
    *,
    task: Task,
    source_post: SourcePost,
    configuration: SystemConfiguration,
    exc: Exception,
    raw_response: object | None,
    context: dict[str, object],
) -> dict[str, int | str]:
    """Reschedule while retries remain, then store the error permanently."""

    retries = getattr(task.request, "retries", 0)
    if retries < configuration.retry_count:
        countdown = min(BASE_RETRY_SECONDS * (2**retries), MAX_RETRY_SECONDS)
        record_monitoring_event(
            component=MonitoringComponent.AI,
            status=MonitoringEventStatus.ERROR,
            source=source_post.source,
            message=(
                f"Временная ошибка анализа поста {source_post.external_id}: {exc}. "
                f"Повтор через {countdown} сек."
            ),
            error_type=type(exc).__name__,
            task_id=task_id(task),
        )
        logger.warning(
            "Temporary or invalid LLM response; retry scheduled.",
            extra={
                **context,
                "event": "analysis.retry_scheduled",
                "status": "retry",
                "error_type": type(exc).__name__,
            },
        )
        raise task.retry(
            exc=exc,
            countdown=countdown,
            max_retries=configuration.retry_count,
        )

    analysis = save_failed_analysis(
        source_post_id=source_post.pk,
        configuration=configuration,
        error=str(exc),
        raw_response=raw_response,
    )
    logger.error(
        "Post analysis retries exhausted.",
        extra={
            **context,
            "event": "analysis.retries_exhausted",
            "analysis_id": analysis.pk,
            "status": "failed",
            "error_type": type(exc).__name__,
        },
    )
    _record_failure_event(task=task, source_post=source_post, exc=exc)
    return failure_result(source_post_id=source_post.pk, analysis=analysis)


def failure_result(
    *,
    source_post_id: int,
    analysis: Analysis,
) -> dict[str, int | str | bool]:
    if analysis.is_successful:
        return {
            "status": "already_analyzed",
            "source_post_id": source_post_id,
            "analysis_id": analysis.pk,
            "is_relevant": bool(analysis.is_relevant),
        }
    return {
        "status": "failed",
        "source_post_id": source_post_id,
        "analysis_id": analysis.pk,
    }


def _record_failure_event(
    *,
    task: Task,
    source_post: SourcePost,
    exc: Exception,
) -> None:
    record_monitoring_event(
        component=MonitoringComponent.AI,
        status=MonitoringEventStatus.ERROR,
        source=source_post.source,
        message=f"Ошибка анализа поста {source_post.external_id}: {exc}",
        error_type=type(exc).__name__,
        task_id=task_id(task),
    )
