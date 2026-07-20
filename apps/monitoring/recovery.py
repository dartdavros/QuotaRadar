"""Recovery of queued work that outlived its Celery execution window."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta

from django.conf import settings
from django.db.models import Q
from django.utils import timezone

from apps.analysis.models import Analysis
from apps.sources.models import SourcePost, SourcePostProcessingStatus
from apps.telegram.models import Delivery, DeliveryStatus

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class RecoveryResult:
    fanouts_completed: int
    analyses_queued: int
    deliveries_queued: int
    fanout_errors: int
    analysis_dispatch_errors: int
    delivery_dispatch_errors: int


def recover_orphaned_work() -> RecoveryResult:
    """Requeue stale analysis and delivery records without exposing secrets."""

    fanouts_completed, fanout_errors = _recover_delivery_fanouts()
    analyses_queued, analysis_errors = _recover_analyses()
    deliveries_queued, delivery_errors = _recover_deliveries()
    return RecoveryResult(
        fanouts_completed=fanouts_completed,
        analyses_queued=analyses_queued,
        deliveries_queued=deliveries_queued,
        fanout_errors=fanout_errors,
        analysis_dispatch_errors=analysis_errors,
        delivery_dispatch_errors=delivery_errors,
    )


def _recover_delivery_fanouts() -> tuple[int, int]:
    from apps.telegram.services import queue_analysis_deliveries

    analysis_ids = list(
        Analysis.objects.filter(
            is_relevant=True,
            error="",
            delivery_fanout_completed_at__isnull=True,
        )
        .order_by("created_at", "pk")
        .values_list("pk", flat=True)
    )
    completed = 0
    errors = 0
    for analysis_id in analysis_ids:
        try:
            queue_analysis_deliveries(analysis_id)
        except Exception as exc:
            errors += 1
            logger.error(
                "Delivery fan-out recovery failed.",
                extra={
                    "event": "monitoring.fanout_recovery_failed",
                    "analysis_id": analysis_id,
                    "status": "failed",
                    "error_type": type(exc).__name__,
                },
            )
            continue
        completed += 1
    return completed, errors


def _recover_analyses() -> tuple[int, int]:
    from apps.analysis.tasks import analyze_post

    cutoff = timezone.now() - timedelta(
        seconds=settings.QUOTARADAR_ANALYSIS_STALE_SECONDS
    )
    stale_ids = list(
        SourcePost.objects.filter(
            processing_status=SourcePostProcessingStatus.QUEUED,
        )
        .filter(
            Q(processing_started_at__isnull=True) | Q(processing_started_at__lte=cutoff)
        )
        .order_by("processing_started_at", "pk")
        .values_list("pk", flat=True)
    )

    queued = 0
    errors = 0
    for source_post_id in stale_ids:
        claimed = (
            SourcePost.objects.filter(
                pk=source_post_id,
                processing_status=SourcePostProcessingStatus.QUEUED,
            )
            .filter(
                Q(processing_started_at__isnull=True)
                | Q(processing_started_at__lte=cutoff)
            )
            .update(
                processing_started_at=timezone.now(),
                last_error="",
            )
        )
        if not claimed:
            continue
        try:
            analyze_post.delay(source_post_id)
        except Exception as exc:
            errors += 1
            SourcePost.objects.filter(pk=source_post_id).update(
                processing_started_at=None,
                last_error="Analysis recovery task could not be queued.",
            )
            logger.error(
                "Analysis recovery task could not be queued.",
                extra={
                    "event": "monitoring.analysis_recovery_dispatch_failed",
                    "source_post_id": source_post_id,
                    "status": "failed",
                    "error_type": type(exc).__name__,
                },
            )
            continue
        queued += 1
    return queued, errors


def _recover_deliveries() -> tuple[int, int]:
    from apps.telegram.tasks import deliver_analysis

    now = timezone.now()
    cutoff = now - timedelta(seconds=settings.QUOTARADAR_DELIVERY_STALE_SECONDS)
    stale = list(
        Delivery.objects.filter(status=DeliveryStatus.PENDING)
        .filter(Q(next_attempt_at__isnull=True) | Q(next_attempt_at__lte=now))
        .filter(
            Q(last_attempt_at__lte=cutoff)
            | Q(last_attempt_at__isnull=True, created_at__lte=cutoff)
        )
        .order_by("last_attempt_at", "created_at", "pk")
        .values_list("pk", "analysis_id", "target_id")
    )

    queued = 0
    errors = 0
    for delivery_id, analysis_id, target_id in stale:
        if not Delivery.objects.filter(
            pk=delivery_id,
            status=DeliveryStatus.PENDING,
        ).exists():
            continue
        try:
            deliver_analysis.delay(analysis_id, target_id)
        except Exception as exc:
            errors += 1
            Delivery.objects.filter(
                pk=delivery_id,
                status=DeliveryStatus.PENDING,
            ).update(last_error="Delivery recovery task could not be queued.")
            logger.error(
                "Delivery recovery task could not be queued.",
                extra={
                    "event": "monitoring.delivery_recovery_dispatch_failed",
                    "analysis_id": analysis_id,
                    "delivery_target_id": target_id,
                    "delivery_id": delivery_id,
                    "status": "failed",
                    "error_type": type(exc).__name__,
                },
            )
            continue
        queued += 1
    return queued, errors
