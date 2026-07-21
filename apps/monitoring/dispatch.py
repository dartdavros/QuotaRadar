"""Dispatch source posts to the analysis queue."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Iterable

from django.utils import timezone

from apps.analysis.tasks import analyze_post
from apps.sources.models import Source, SourcePost, SourcePostProcessingStatus

from .events import record_monitoring_event
from .models import MonitoringComponent, MonitoringEventStatus

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class AnalysisDispatchResult:
    requested: int
    queued: int
    skipped: int
    dispatch_failed: int


def enqueue_pending_posts(*, source: Source, task_id: str) -> int:
    """Queue every received post for the source, including prior backlog."""

    post_ids = list(
        SourcePost.objects.filter(
            source_id=source.pk,
            processing_status=SourcePostProcessingStatus.RECEIVED,
        )
        .order_by("published_at", "pk")
        .values_list("pk", flat=True)
    )
    result = enqueue_posts_for_analysis(
        post_ids=post_ids,
        eligible_statuses=(SourcePostProcessingStatus.RECEIVED,),
        task_id=task_id,
    )
    return result.queued


def enqueue_posts_for_analysis(
    *,
    post_ids: Iterable[int],
    eligible_statuses: tuple[str, ...],
    task_id: str = "",
) -> AnalysisDispatchResult:
    """Claim and queue exactly the requested posts with eligible statuses."""

    requested_ids = tuple(dict.fromkeys(post_ids))
    candidates = list(
        SourcePost.objects.select_related("source")
        .filter(pk__in=requested_ids, processing_status__in=eligible_statuses)
        .order_by("published_at", "pk")
    )
    queued = 0
    skipped = len(requested_ids) - len(candidates)
    dispatch_failed = 0

    for post in candidates:
        previous_status = post.processing_status
        previous_started_at = post.processing_started_at
        previous_error = post.last_error
        claimed = SourcePost.objects.filter(
            pk=post.pk,
            processing_status=previous_status,
        ).update(
            processing_status=SourcePostProcessingStatus.QUEUED,
            processing_started_at=timezone.now(),
            last_error="",
        )
        if not claimed:
            skipped += 1
            continue

        try:
            analyze_post.delay(post.pk)
        except Exception as exc:
            dispatch_failed += 1
            SourcePost.objects.filter(
                pk=post.pk,
                processing_status=SourcePostProcessingStatus.QUEUED,
            ).update(
                processing_status=previous_status,
                processing_started_at=previous_started_at,
                last_error=previous_error or "Analysis task could not be queued.",
            )
            record_monitoring_event(
                component=MonitoringComponent.AI,
                status=MonitoringEventStatus.ERROR,
                source=post.source,
                message=f"Не удалось поставить пост {post.pk} в очередь анализа: {exc}",
                error_type=type(exc).__name__,
                task_id=task_id,
            )
            logger.exception(
                "Analysis task could not be queued.",
                extra={
                    "event": "monitoring.analysis_dispatch_failed",
                    "task_id": task_id,
                    "source_id": post.source_id,
                    "source_post_id": post.pk,
                    "status": "failed",
                    "error_type": type(exc).__name__,
                },
            )
            continue

        queued += 1

    return AnalysisDispatchResult(
        requested=len(requested_ids),
        queued=queued,
        skipped=skipped,
        dispatch_failed=dispatch_failed,
    )
