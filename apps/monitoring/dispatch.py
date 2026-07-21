"""Dispatch unprocessed source posts to the analysis queue."""

from __future__ import annotations

import logging

from django.utils import timezone

from apps.analysis.tasks import analyze_post
from apps.sources.models import Source, SourcePost, SourcePostProcessingStatus

from .events import record_monitoring_event
from .models import MonitoringComponent, MonitoringEventStatus

logger = logging.getLogger(__name__)


def enqueue_pending_posts(*, source: Source, task_id: str) -> int:
    """Queue every unprocessed post for the source, including prior backlog."""

    post_ids = list(
        SourcePost.objects.filter(
            source_id=source.pk,
            processing_status=SourcePostProcessingStatus.RECEIVED,
        )
        .order_by("published_at", "pk")
        .values_list("pk", flat=True)
    )
    queued = 0
    for post_id in post_ids:
        claimed = SourcePost.objects.filter(
            pk=post_id,
            processing_status=SourcePostProcessingStatus.RECEIVED,
        ).update(
            processing_status=SourcePostProcessingStatus.QUEUED,
            processing_started_at=timezone.now(),
            last_error="",
        )
        if not claimed:
            continue
        try:
            analyze_post.delay(post_id)
        except Exception as exc:
            SourcePost.objects.filter(
                pk=post_id,
                processing_status=SourcePostProcessingStatus.QUEUED,
            ).update(
                processing_status=SourcePostProcessingStatus.RECEIVED,
                processing_started_at=None,
                last_error="Analysis task could not be queued.",
            )
            record_monitoring_event(
                component=MonitoringComponent.AI,
                status=MonitoringEventStatus.ERROR,
                source=source,
                message=f"Не удалось поставить пост {post_id} в очередь анализа: {exc}",
                error_type=type(exc).__name__,
                task_id=task_id,
            )
            logger.exception(
                "Analysis task could not be queued.",
                extra={
                    "event": "monitoring.analysis_dispatch_failed",
                    "task_id": task_id,
                    "source_id": source.pk,
                    "source_post_id": post_id,
                    "status": "failed",
                    "error_type": type(exc).__name__,
                },
            )
            continue
        queued += 1
    return queued
