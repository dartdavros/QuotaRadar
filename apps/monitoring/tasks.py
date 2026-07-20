"""Celery tasks for periodic, idempotent X source polling."""

from __future__ import annotations

import logging

from celery import Task, shared_task

from apps.analysis.tasks import analyze_post
from apps.configuration.models import SystemConfiguration
from apps.sources.models import Source, SourcePost, SourcePostProcessingStatus

from .locks import source_poll_lock
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
_BASE_RETRY_SECONDS = 30
_MAX_RETRY_SECONDS = 900


@shared_task(name="monitoring.healthcheck")
def healthcheck() -> dict[str, str]:
    """Return a deterministic response proving that the worker accepts tasks."""

    return {"status": "ok", "service": "worker"}


@shared_task(bind=True, name="monitoring.poll_sources")
def poll_sources(self: Task) -> dict[str, int | str]:
    """Resolve missing source IDs and enqueue one polling task per active source."""

    configuration = SystemConfiguration.load()
    if not configuration.monitoring_enabled:
        return {"status": "disabled", "queued": 0}

    sources = list(Source.objects.filter(enabled=True).order_by("pk"))
    if not sources:
        return {"status": "ok", "queued": 0}

    try:
        with XApiClient() as client:
            resolution = resolve_source_user_ids(client=client, sources=sources)
    except _PERMANENT_X_ERRORS as exc:
        record_source_error([source.pk for source in sources], str(exc))
        logger.error("Source user ID resolution failed: %s", exc)
        return {"status": "error", "queued": 0}
    except XApiRateLimitError as exc:
        record_source_error([source.pk for source in sources], str(exc))
        _retry_task(self, exc, configuration.retry_count, exc.retry_after_seconds())
    except XApiTemporaryError as exc:
        record_source_error([source.pk for source in sources], str(exc))
        _retry_task(self, exc, configuration.retry_count, _retry_countdown(self))

    queued = 0
    resolved_ids = set(resolution.resolved_source_ids)
    for source in sources:
        if source.pk in resolved_ids:
            poll_source.delay(source.pk)
            queued += 1
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

    configuration = SystemConfiguration.load()
    if not configuration.monitoring_enabled:
        return {"status": "disabled", "source_id": source_id}

    with source_poll_lock(source_id) as acquired:
        if not acquired:
            return {"status": "locked", "source_id": source_id}
        try:
            with XApiClient() as client:
                if not source.x_user_id:
                    resolution = resolve_source_user_ids(
                        client=client, sources=[source]
                    )
                    if source_id in resolution.unresolved_source_ids:
                        return {"status": "unresolved", "source_id": source_id}
                source.refresh_from_db()
                result = ingest_source_posts(source=source, client=client)
                queued_analyses = _enqueue_pending_posts(source_id)
        except _PERMANENT_X_ERRORS as exc:
            record_source_error([source_id], str(exc))
            logger.error("Source polling failed for source_id=%s: %s", source_id, exc)
            return {"status": "error", "source_id": source_id}
        except XApiRateLimitError as exc:
            record_source_error([source_id], str(exc))
            _retry_task(self, exc, configuration.retry_count, exc.retry_after_seconds())
        except XApiTemporaryError as exc:
            record_source_error([source_id], str(exc))
            _retry_task(self, exc, configuration.retry_count, _retry_countdown(self))

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


def _enqueue_pending_posts(source_id: int) -> int:
    """Queue every unprocessed post for the source, including prior backlog."""

    post_ids = list(
        SourcePost.objects.filter(
            source_id=source_id,
            processing_status=SourcePostProcessingStatus.RECEIVED,
        )
        .order_by("published_at", "pk")
        .values_list("pk", flat=True)
    )
    queued = 0
    for post_id in post_ids:
        analyze_post.delay(post_id)
        SourcePost.objects.filter(
            pk=post_id,
            processing_status=SourcePostProcessingStatus.RECEIVED,
        ).update(processing_status=SourcePostProcessingStatus.QUEUED)
        queued += 1
    return queued


_PERMANENT_X_ERRORS = (
    XApiConfigurationError,
    XApiAuthenticationError,
    XApiForbiddenError,
    XApiNotFoundError,
    XApiResponseError,
)


def _retry_countdown(task: Task) -> int:
    retries = getattr(task.request, "retries", 0)
    return min(_BASE_RETRY_SECONDS * (2**retries), _MAX_RETRY_SECONDS)


def _retry_task(task: Task, exc: Exception, retry_count: int, countdown: int) -> None:
    logger.warning("Temporary X API failure; retry scheduled: %s", exc)
    raise task.retry(
        exc=exc,
        countdown=countdown,
        max_retries=retry_count,
    )
