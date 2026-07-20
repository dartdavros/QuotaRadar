"""Celery tasks for isolated, idempotent Telegram delivery."""

from __future__ import annotations

import logging

from celery import Task, shared_task
from django.db import transaction
from django.utils import timezone

from apps.configuration.models import SystemConfiguration

from .client import (
    TelegramAuthenticationError,
    TelegramBotApiClient,
    TelegramConfigurationError,
    TelegramPermanentChatError,
    TelegramResponseError,
    TelegramTemporaryError,
)
from .locks import delivery_send_lock
from .models import Delivery, DeliveryStatus, DeliveryTargetType
from .services import DeliveryMessageError, format_delivery_message

logger = logging.getLogger(__name__)
_BASE_RETRY_SECONDS = 30
_MAX_RETRY_SECONDS = 900


@shared_task(bind=True, name="telegram.deliver_analysis")
def deliver_analysis(
    self: Task,
    analysis_id: int,
    target_id: int,
) -> dict[str, int | str]:
    delivery = _load_delivery(analysis_id=analysis_id, target_id=target_id)
    if delivery is None:
        return {
            "status": "missing",
            "analysis_id": analysis_id,
            "target_id": target_id,
        }

    with delivery_send_lock(delivery.pk) as acquired:
        if not acquired:
            return _result("locked", delivery)
        delivery = _load_delivery(analysis_id=analysis_id, target_id=target_id)
        if delivery is None:
            return {
                "status": "missing",
                "analysis_id": analysis_id,
                "target_id": target_id,
            }
        return _deliver_locked(task=self, delivery=delivery)


def _deliver_locked(*, task: Task, delivery: Delivery) -> dict[str, int | str]:
    if delivery.status == DeliveryStatus.SENT:
        return _result("already_sent", delivery)
    if not delivery.target.enabled:
        _mark_failed(delivery.pk, "Delivery target is disabled.")
        return _result("disabled", delivery)

    try:
        text = format_delivery_message(delivery.analysis)
    except DeliveryMessageError as exc:
        _mark_failed(delivery.pk, str(exc))
        return _result("failed", delivery)

    _increment_attempts(delivery.pk)
    try:
        with TelegramBotApiClient() as client:
            message_id = client.send_message(
                chat_id=delivery.target.telegram_chat_id,
                text=text,
            )
    except TelegramTemporaryError as exc:
        _mark_failed(delivery.pk, str(exc))
        return _retry_or_fail(task=task, delivery=delivery, exc=exc)
    except TelegramPermanentChatError as exc:
        _mark_permanent_chat_failure(delivery.pk, str(exc))
        return _result("failed", delivery)
    except _PERMANENT_DELIVERY_ERRORS as exc:
        _mark_failed(delivery.pk, str(exc))
        logger.error(
            "Telegram delivery failed for analysis_id=%s target_id=%s: %s",
            delivery.analysis_id,
            delivery.target_id,
            exc,
        )
        return _result("failed", delivery)

    _mark_sent(delivery.pk, message_id)
    return _result("sent", delivery)


_PERMANENT_DELIVERY_ERRORS = (
    TelegramConfigurationError,
    TelegramAuthenticationError,
    TelegramResponseError,
)


def _load_delivery(*, analysis_id: int, target_id: int) -> Delivery | None:
    return (
        Delivery.objects.select_related("analysis__source_post", "target")
        .filter(analysis_id=analysis_id, target_id=target_id)
        .first()
    )


def _retry_or_fail(
    *,
    task: Task,
    delivery: Delivery,
    exc: TelegramTemporaryError,
) -> dict[str, int | str]:
    configuration = SystemConfiguration.load()
    retries = getattr(task.request, "retries", 0)
    if retries < configuration.retry_count:
        countdown = exc.retry_after or min(
            _BASE_RETRY_SECONDS * (2**retries), _MAX_RETRY_SECONDS
        )
        logger.warning(
            "Temporary Telegram delivery failure; retry scheduled for "
            "analysis_id=%s target_id=%s.",
            delivery.analysis_id,
            delivery.target_id,
        )
        raise task.retry(
            exc=exc,
            countdown=countdown,
            max_retries=configuration.retry_count,
        )
    return _result("failed", delivery)


def _increment_attempts(delivery_id: int) -> None:
    with transaction.atomic():
        delivery = Delivery.objects.select_for_update().get(pk=delivery_id)
        if delivery.status == DeliveryStatus.SENT:
            return
        delivery.attempts += 1
        delivery.save(update_fields=("attempts",))


def _mark_sent(delivery_id: int, message_id: str) -> None:
    Delivery.objects.filter(pk=delivery_id).exclude(status=DeliveryStatus.SENT).update(
        status=DeliveryStatus.SENT,
        telegram_message_id=message_id,
        sent_at=timezone.now(),
        last_error="",
    )


def _mark_failed(delivery_id: int, error: str) -> None:
    Delivery.objects.filter(pk=delivery_id).exclude(status=DeliveryStatus.SENT).update(
        status=DeliveryStatus.FAILED,
        last_error=error,
    )


def _mark_permanent_chat_failure(delivery_id: int, error: str) -> None:
    with transaction.atomic():
        delivery = (
            Delivery.objects.select_for_update()
            .select_related("target")
            .get(pk=delivery_id)
        )
        if delivery.status == DeliveryStatus.SENT:
            return
        delivery.status = DeliveryStatus.FAILED
        delivery.last_error = error
        delivery.save(update_fields=("status", "last_error"))
        if delivery.target.target_type == DeliveryTargetType.PRIVATE_CHAT:
            delivery.target.enabled = False
            delivery.target.save(update_fields=("enabled", "updated_at"))


def _result(status: str, delivery: Delivery) -> dict[str, int | str]:
    return {
        "status": status,
        "delivery_id": delivery.pk,
        "analysis_id": delivery.analysis_id,
        "target_id": delivery.target_id,
    }
