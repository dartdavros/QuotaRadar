"""Message formatting and idempotent delivery fan-out."""

from __future__ import annotations

from dataclasses import dataclass

from django.db import transaction

from apps.analysis.models import Analysis

from .models import Delivery, DeliveryStatus, DeliveryTarget

TELEGRAM_MESSAGE_LIMIT = 4096


class DeliveryMessageError(ValueError):
    """An analysis cannot be represented as a valid Telegram message."""


@dataclass(frozen=True, slots=True)
class QueuedDeliveries:
    analysis_id: int
    delivery_ids: tuple[int, ...]


def format_delivery_message(analysis: Analysis) -> str:
    if analysis.is_relevant is not True:
        raise DeliveryMessageError("Only relevant analyses can be delivered.")
    title = analysis.title_ru.strip()
    message = analysis.message_ru.strip()
    source_url = analysis.source_post.source_url.strip()
    if not title or not message or not source_url:
        raise DeliveryMessageError("Relevant analysis is missing delivery content.")
    payload = f"{title}\n\n{message}\n\nИсточник: {source_url}"
    if len(payload) > TELEGRAM_MESSAGE_LIMIT:
        raise DeliveryMessageError("Telegram message exceeds 4096 characters.")
    return payload


@transaction.atomic
def queue_analysis_deliveries(analysis_id: int) -> QueuedDeliveries:
    analysis = Analysis.objects.select_related("source_post").get(pk=analysis_id)
    if analysis.is_relevant is not True:
        return QueuedDeliveries(analysis_id=analysis_id, delivery_ids=())

    created_ids: list[int] = []
    for target in DeliveryTarget.objects.filter(enabled=True).only("pk"):
        delivery, created = Delivery.objects.get_or_create(
            analysis=analysis,
            target=target,
            defaults={"status": DeliveryStatus.PENDING},
        )
        if created or delivery.status == DeliveryStatus.FAILED:
            created_ids.append(delivery.pk)

    delivery_ids = tuple(created_ids)
    if delivery_ids:
        transaction.on_commit(lambda: _dispatch_deliveries(delivery_ids))
    return QueuedDeliveries(analysis_id=analysis_id, delivery_ids=delivery_ids)


def _dispatch_deliveries(delivery_ids: tuple[int, ...]) -> None:
    from .tasks import deliver_analysis

    deliveries = Delivery.objects.filter(pk__in=delivery_ids).values_list(
        "pk", "analysis_id", "target_id"
    )
    for delivery_id, analysis_id, target_id in deliveries:
        try:
            deliver_analysis.delay(analysis_id, target_id)
        except Exception:
            Delivery.objects.filter(
                pk=delivery_id,
                status=DeliveryStatus.PENDING,
            ).update(
                status=DeliveryStatus.FAILED,
                last_error="Delivery task could not be queued.",
            )
