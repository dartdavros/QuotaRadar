"""Message formatting and idempotent delivery fan-out."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from django.db import transaction
from django.utils import timezone

from apps.analysis.models import Analysis
from apps.sources.models import Feed
from apps.monitoring.events import record_monitoring_event
from apps.monitoring.models import MonitoringComponent, MonitoringEventStatus

from .freshness import stale
from .models import Delivery, DeliveryStatus, DeliveryTarget

from .formatting import DeliveryMessageError, format_delivery_message

@dataclass(frozen=True, slots=True)
class QueuedDeliveries:
    analysis_id: int
    delivery_ids: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class DeliveryDispatchResult:
    requested: int
    queued: int
    skipped: int
    dispatch_failed: int


@transaction.atomic
def queue_analysis_deliveries(analysis_id: int) -> QueuedDeliveries:
    analysis = (
        Analysis.objects.select_for_update()
        .select_related("source_post")
        .get(pk=analysis_id)
    )
    if analysis.is_relevant is not True:
        return QueuedDeliveries(analysis_id=analysis_id, delivery_ids=())
    if analysis.delivery_fanout_completed_at is not None:
        return QueuedDeliveries(analysis_id=analysis_id, delivery_ids=())
    if stale(analysis.source_post.published_at, timezone.now()):
        # Backlog from a bootstrap or an outage: no delivery row is created, so nothing can ever send it.
        analysis.delivery_fanout_completed_at = timezone.now()
        analysis.save(update_fields=("delivery_fanout_completed_at", "updated_at"))
        record_monitoring_event(
            component=MonitoringComponent.TELEGRAM,
            status=MonitoringEventStatus.SUCCESS,
            source=analysis.source_post.source,
            message=f"Анализ {analysis.pk} не отправлен: пост старше 30 минут.",
        )
        return QueuedDeliveries(analysis_id=analysis_id, delivery_ids=())

    queued_ids: list[int] = []
    for target in DeliveryTarget.objects.filter(enabled=True, feed=Feed.QUOTA).only("pk"):
        delivery, created = Delivery.objects.get_or_create(
            analysis=analysis,
            target=target,
            defaults={"status": DeliveryStatus.PENDING},
        )
        if created:
            queued_ids.append(delivery.pk)

    analysis.delivery_fanout_completed_at = timezone.now()
    analysis.save(update_fields=("delivery_fanout_completed_at", "updated_at"))

    delivery_ids = tuple(queued_ids)
    if delivery_ids:
        transaction.on_commit(lambda: _dispatch_deliveries(delivery_ids))
    return QueuedDeliveries(analysis_id=analysis_id, delivery_ids=delivery_ids)


def _dispatch_deliveries(delivery_ids: tuple[int, ...]) -> None:
    from .tasks import deliver_analysis

    deliveries = Delivery.objects.filter(
        pk__in=delivery_ids,
        status=DeliveryStatus.PENDING,
    ).values_list("pk", "analysis_id", "target_id")
    for delivery_id, analysis_id, target_id in deliveries:
        try:
            deliver_analysis.delay(analysis_id, target_id)
        except Exception:
            Delivery.objects.filter(
                pk=delivery_id,
                status=DeliveryStatus.PENDING,
            ).update(last_error="Delivery task could not be queued.")


def requeue_failed_deliveries(
    *,
    delivery_ids: Iterable[int],
    task_id: str = "",
) -> DeliveryDispatchResult:
    """Reset and dispatch exactly the requested failed Telegram deliveries."""

    requested_ids = tuple(dict.fromkeys(delivery_ids))
    candidates = list(
        Delivery.objects.select_related(
            "analysis__source_post__source",
            "target",
        )
        .filter(pk__in=requested_ids, status=DeliveryStatus.FAILED)
        .order_by("pk")
    )
    queued = 0
    skipped = len(requested_ids) - len(candidates)
    dispatch_failed = 0

    from .tasks import deliver_analysis

    for delivery in candidates:
        previous_state = {
            "status": delivery.status,
            "telegram_message_id": delivery.telegram_message_id,
            "attempts": delivery.attempts,
            "last_attempt_at": delivery.last_attempt_at,
            "next_attempt_at": delivery.next_attempt_at,
            "sent_at": delivery.sent_at,
            "last_error": delivery.last_error,
        }
        claimed = Delivery.objects.filter(
            pk=delivery.pk,
            status=DeliveryStatus.FAILED,
        ).update(
            status=DeliveryStatus.PENDING,
            telegram_message_id="",
            attempts=0,
            last_attempt_at=None,
            next_attempt_at=None,
            sent_at=None,
            last_error="",
            updated_at=timezone.now(),
        )
        if not claimed:
            skipped += 1
            continue

        try:
            deliver_analysis.delay(delivery.analysis_id, delivery.target_id)
        except Exception as exc:
            dispatch_failed += 1
            Delivery.objects.filter(
                pk=delivery.pk,
                status=DeliveryStatus.PENDING,
                attempts=0,
            ).update(
                **previous_state,
                updated_at=timezone.now(),
            )
            record_monitoring_event(
                component=MonitoringComponent.TELEGRAM,
                status=MonitoringEventStatus.ERROR,
                source=delivery.analysis.source_post.source,
                message=(
                    f"Не удалось вернуть доставку {delivery.pk} "
                    f"в очередь Telegram: {exc}"
                ),
                error_type=type(exc).__name__,
                task_id=task_id,
            )
            continue

        queued += 1

    return DeliveryDispatchResult(
        requested=len(requested_ids),
        queued=queued,
        skipped=skipped,
        dispatch_failed=dispatch_failed,
    )
