"""Celery tasks for periodic, idempotent X source polling and recovery."""

from __future__ import annotations

import logging

from celery import Task, shared_task

from apps.configuration.models import SystemConfiguration
from apps.sources.models import Source

from .dispatch import enqueue_pending_posts
from .events import record_monitoring_event
from .locks import source_poll_lock
from .models import MonitoringComponent, MonitoringEventStatus
from .recovery import recover_orphaned_work as run_recovery
from .retries import retry_countdown, retry_x_task
from .services import ingest_source_posts, record_source_error, resolve_source_user_ids
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


@shared_task(name="monitoring.healthcheck")
def healthcheck() -> dict[str, str]:
    """Return a deterministic response proving that the worker accepts tasks."""
    return {"status": "ok", "service": "worker"}


@shared_task(bind=True, name="monitoring.poll_sources")
def poll_sources(self: Task) -> dict[str, int | str]:
    """Resolve missing source IDs and enqueue one polling task per active source."""
    task_id = _task_id(self)
    configuration = SystemConfiguration.load()
    if not configuration.monitoring_enabled:
        logger.info(
            "Source polling is disabled.",
            extra={
                "event": "monitoring.poll_sources_disabled",
                "task_id": task_id,
                "status": "disabled",
            },
        )
        return {"status": "disabled", "queued": 0}

    sources = list(Source.objects.filter(enabled=True).order_by("pk"))
    if not sources:
        return {"status": "ok", "queued": 0}

    try:
        with XApiClient() as client:
            resolution = resolve_source_user_ids(client=client, sources=sources)
    except _PERMANENT_X_ERRORS as exc:
        record_source_error([source.pk for source in sources], str(exc))
        for source in sources:
            record_monitoring_event(
                component=MonitoringComponent.X,
                status=MonitoringEventStatus.ERROR,
                source=source,
                message=str(exc),
                error_type=type(exc).__name__,
                task_id=task_id,
            )
        logger.error(
            "Source user ID resolution failed.",
            extra={
                "event": "monitoring.source_resolution_failed",
                "task_id": task_id,
                "status": "failed",
                "error_type": type(exc).__name__,
            },
        )
        return {"status": "error", "queued": 0}
    except XApiRateLimitError as exc:
        record_source_error([source.pk for source in sources], str(exc))
        retry_x_task(
            self,
            exc,
            configuration.retry_count,
            exc.retry_after_seconds(),
            sources=sources,
        )
    except XApiTemporaryError as exc:
        record_source_error([source.pk for source in sources], str(exc))
        retry_x_task(
            self,
            exc,
            configuration.retry_count,
            retry_countdown(self),
            sources=sources,
        )

    source_by_id = {source.pk: source for source in sources}
    for source_id in resolution.unresolved_source_ids:
        source = source_by_id[source_id]
        record_monitoring_event(
            component=MonitoringComponent.X,
            status=MonitoringEventStatus.ERROR,
            source=source,
            message=source.last_error or "Не удалось определить X User ID.",
            error_type="XUserResolutionError",
            task_id=task_id,
        )

    queued = 0
    resolved_ids = set(resolution.resolved_source_ids)
    for source in sources:
        if source.pk in resolved_ids:
            poll_source.delay(source.pk)
            queued += 1
    logger.info(
        "Source polling tasks queued.",
        extra={
            "event": "monitoring.poll_sources_queued",
            "task_id": task_id,
            "status": "ok",
        },
    )
    return {"status": "ok", "queued": queued}


@shared_task(bind=True, name="monitoring.poll_source")
def poll_source(self: Task, source_id: int) -> dict[str, int | str]:
    """Poll one X source under a Redis lock and persist all returned pages."""
    try:
        source = Source.objects.get(pk=source_id)
    except Source.DoesNotExist:
        return {"status": "missing", "source_id": source_id}
    if not source.enabled:
        return {"status": "disabled", "source_id": source_id}

    context = {
        "event": "monitoring.source_poll_started",
        "task_id": _task_id(self),
        "source_id": source_id,
    }
    logger.info("Source polling started.", extra=context)

    config = SystemConfiguration.load()
    if not config.monitoring_enabled:
        return {"status": "disabled", "source_id": source_id}

    with source_poll_lock(source_id) as acquired:
        if not acquired:
            logger.info(
                "Source polling skipped because the lock is held.",
                extra={
                    **context,
                    "event": "monitoring.source_poll_locked",
                    "status": "locked",
                },
            )
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
                            or "Не удалось определить X User ID.",
                            error_type="XUserResolutionError",
                            task_id=_task_id(self),
                        )
                        return {"status": "unresolved", "source_id": source_id}
                source.refresh_from_db()
                result = ingest_source_posts(source, client, config)
                queued_analyses = enqueue_pending_posts(
                    source=source,
                    task_id=_task_id(self),
                )
        except _PERMANENT_X_ERRORS as exc:
            record_source_error([source_id], str(exc))
            record_monitoring_event(
                component=MonitoringComponent.X,
                status=MonitoringEventStatus.ERROR,
                source=source,
                message=str(exc),
                error_type=type(exc).__name__,
                task_id=_task_id(self),
            )
            logger.error(
                "Source polling failed permanently.",
                extra={
                    **context,
                    "event": "monitoring.source_poll_failed",
                    "status": "failed",
                    "error_type": type(exc).__name__,
                },
            )
            return {"status": "error", "source_id": source_id}
        except XApiRateLimitError as exc:
            record_source_error([source_id], str(exc))
            retry_x_task(
                self,
                exc,
                config.retry_count,
                exc.retry_after_seconds(),
                sources=[source],
            )
        except XApiTemporaryError as exc:
            record_source_error([source_id], str(exc))
            retry_x_task(
                self,
                exc,
                config.retry_count,
                retry_countdown(self),
                sources=[source],
            )

    logger.info(
        "Source polling completed.",
        extra={
            **context,
            "event": "monitoring.source_poll_completed",
            "status": "ok",
        },
    )
    record_monitoring_event(
        component=MonitoringComponent.X,
        status=MonitoringEventStatus.SUCCESS,
        source=source,
        message=(
            f"Проверка завершена. Новых постов: {result.created_posts}; "
            f"уже известных: {result.existing_posts}; "
            f"поставлено на анализ: {queued_analyses}."
        ),
        task_id=_task_id(self),
    )
    return {
        "status": "ok",
        "source_id": result.source_id,
        "pages": result.pages,
        "created_posts": result.created_posts,
        "existing_posts": result.existing_posts,
        "ignored_retweets": result.ignored_retweets,
        "last_post_id": result.last_post_id,
        "queued_analyses": queued_analyses,
    }


@shared_task(bind=True, name="monitoring.recover_orphaned_work")
def recover_orphaned_work(self: Task) -> dict[str, int | str]:
    """Requeue stale work records whose original Celery messages were lost."""
    result = run_recovery()
    status = (
        "partial"
        if (
            result.fanout_errors
            or result.analysis_dispatch_errors
            or result.delivery_dispatch_errors
        )
        else "ok"
    )
    logger.info(
        "Orphaned work recovery completed.",
        extra={
            "event": "monitoring.recovery_completed",
            "task_id": _task_id(self),
            "status": status,
        },
    )
    return {
        "status": status,
        "fanouts_completed": result.fanouts_completed,
        "analyses_queued": result.analyses_queued,
        "deliveries_queued": result.deliveries_queued,
        "fanout_errors": result.fanout_errors,
        "analysis_dispatch_errors": result.analysis_dispatch_errors,
        "delivery_dispatch_errors": result.delivery_dispatch_errors,
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
