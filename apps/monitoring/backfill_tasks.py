"""Celery task for bounded historical X post imports."""

from __future__ import annotations

import logging

from celery import Task, shared_task

from apps.configuration.models import SystemConfiguration
from apps.sources.models import Source, SourcePostProcessingStatus

from .backfill import BackfillUnavailableError, ingest_source_history
from .dispatch import enqueue_posts_for_analysis
from .events import record_monitoring_event
from .locks import source_poll_lock
from .models import MonitoringComponent, MonitoringEventStatus
from .retries import retry_countdown, retry_x_task
from .services import resolve_source_user_ids
from .x_api import (
    XApiAuthenticationError,
    XApiClient,
    XApiConfigurationError,
    XApiForbiddenError,
    XApiNotFoundError,
    XApiRateLimitError,
    XApiResponseError,
    XApiTemporaryError,
)

logger = logging.getLogger(__name__)


@shared_task(bind=True, name="monitoring.backfill_source")
def backfill_source(self: Task, source_id: int) -> dict[str, int | str]:
    """Import and enqueue one historical batch without changing poll cursors."""

    try:
        source = Source.objects.get(pk=source_id)
    except Source.DoesNotExist:
        return {"status": "missing", "source_id": source_id}

    task_id = _task_id(self)
    configuration = SystemConfiguration.load()
    with source_poll_lock(source_id) as acquired:
        if not acquired:
            return {"status": "locked", "source_id": source_id}
        try:
            with XApiClient() as client:
                if not source.x_user_id:
                    resolution = resolve_source_user_ids(
                        client=client,
                        sources=[source],
                    )
                    if source_id in resolution.unresolved_source_ids:
                        record_monitoring_event(
                            component=MonitoringComponent.X,
                            status=MonitoringEventStatus.ERROR,
                            source=source,
                            message=source.last_error
                            or "Не удалось определить X User ID для импорта истории.",
                            error_type="XUserResolutionError",
                            task_id=task_id,
                        )
                        return {"status": "unresolved", "source_id": source_id}
                source.refresh_from_db()
                result = ingest_source_history(source, client, configuration)
                dispatch = enqueue_posts_for_analysis(
                    post_ids=result.created_post_ids,
                    eligible_statuses=(SourcePostProcessingStatus.RECEIVED,),
                    task_id=task_id,
                )
        except BackfillUnavailableError as exc:
            record_monitoring_event(
                component=MonitoringComponent.X,
                status=MonitoringEventStatus.ERROR,
                source=source,
                message=f"Исторический импорт не выполнен: {exc}",
                error_type=type(exc).__name__,
                task_id=task_id,
            )
            return {"status": "unavailable", "source_id": source_id}
        except _PERMANENT_X_ERRORS as exc:
            record_monitoring_event(
                component=MonitoringComponent.X,
                status=MonitoringEventStatus.ERROR,
                source=source,
                message=f"Ошибка исторического импорта: {exc}",
                error_type=type(exc).__name__,
                task_id=task_id,
            )
            logger.error(
                "Historical source import failed permanently.",
                extra={
                    "event": "monitoring.source_backfill_failed",
                    "task_id": task_id,
                    "source_id": source_id,
                    "status": "failed",
                    "error_type": type(exc).__name__,
                },
            )
            return {"status": "error", "source_id": source_id}
        except XApiRateLimitError as exc:
            retry_x_task(
                self,
                exc,
                configuration.retry_count,
                exc.retry_after_seconds(),
                sources=[source],
            )
        except XApiTemporaryError as exc:
            retry_x_task(
                self,
                exc,
                configuration.retry_count,
                retry_countdown(self),
                sources=[source],
            )

    record_monitoring_event(
        component=MonitoringComponent.X,
        status=MonitoringEventStatus.SUCCESS,
        source=source,
        message=(
            f"Исторический импорт завершён. Добавлено постов: "
            f"{result.created_posts}; уже известных: {result.existing_posts}; "
            f"поставлено на анализ: {dispatch.queued}."
        ),
        task_id=task_id,
    )
    return {
        "status": "ok",
        "source_id": source_id,
        "pages": result.pages,
        "created_posts": result.created_posts,
        "existing_posts": result.existing_posts,
        "ignored_retweets": result.ignored_retweets,
        "queued_analyses": dispatch.queued,
        "analysis_dispatch_failed": dispatch.dispatch_failed,
        "history_cursor": result.history_cursor,
    }


_PERMANENT_X_ERRORS = (
    XApiConfigurationError,
    XApiAuthenticationError,
    XApiForbiddenError,
    XApiNotFoundError,
    XApiResponseError,
)


def _task_id(task: Task) -> str:
    return str(getattr(task.request, "id", "") or "")
