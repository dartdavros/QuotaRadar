"""Transactional state changes for Telegram deliveries."""

from __future__ import annotations

from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from .models import Delivery, DeliveryStatus


def increment_attempts(delivery_id: int) -> None:
    now = timezone.now()
    with transaction.atomic():
        delivery = Delivery.objects.select_for_update().get(pk=delivery_id)
        if delivery.status != DeliveryStatus.PENDING:
            return
        delivery.attempts += 1
        delivery.last_attempt_at = now
        delivery.next_attempt_at = None
        delivery.updated_at = now
        delivery.save(
            update_fields=(
                "attempts",
                "last_attempt_at",
                "next_attempt_at",
                "updated_at",
            )
        )


def mark_sent(delivery_id: int, message_id: str) -> None:
    from apps.advertising.services import confirm_placement, lock_target
    now = timezone.now()
    with transaction.atomic():
        lock_target(delivery_id)
        Delivery.objects.filter(pk=delivery_id).exclude(status=DeliveryStatus.SENT).update(
            status=DeliveryStatus.SENT, telegram_message_id=message_id, sent_at=now,
            next_attempt_at=None, updated_at=now, last_error="")
        confirm_placement(delivery_id)


def mark_retry_scheduled(delivery_id: int, error: str, *, countdown: int) -> None:
    from apps.advertising.services import retry_reserved
    retry_reserved(delivery_id)
    now = timezone.now()
    Delivery.objects.filter(
        pk=delivery_id,
        status=DeliveryStatus.PENDING,
    ).update(
        last_error=error,
        next_attempt_at=now + timedelta(seconds=countdown),
        updated_at=now,
    )


@transaction.atomic
def mark_failed(delivery_id: int, error: str) -> None:
    from apps.advertising.services import lock_target, release
    lock_target(delivery_id)
    Delivery.objects.filter(pk=delivery_id).exclude(status=DeliveryStatus.SENT).update(
        status=DeliveryStatus.FAILED,
        last_error=error,
        next_attempt_at=None,
        updated_at=timezone.now(),
    )
    release(delivery_id)


def mark_permanent_chat_failure(delivery_id: int, error: str) -> None:
    from apps.advertising.services import lock_target, release
    with transaction.atomic():
        lock_target(delivery_id)
        delivery = (
            Delivery.objects.select_for_update()
            .select_related("target")
            .get(pk=delivery_id)
        )
        if delivery.status == DeliveryStatus.SENT:
            return
        delivery.status = DeliveryStatus.FAILED
        delivery.last_error = error
        delivery.next_attempt_at = None
        delivery.updated_at = timezone.now()
        delivery.save(
            update_fields=("status", "last_error", "next_attempt_at", "updated_at")
        )
        release(delivery_id)
        if delivery.target.is_private_chat:
            delivery.target.enabled = False
            delivery.target.save(update_fields=("enabled", "updated_at"))
