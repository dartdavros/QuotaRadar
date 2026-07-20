"""Celery tasks for isolated, idempotent Telegram delivery."""

from __future__ import annotations

import logging
from datetime import timedelta

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

    context = {
        "event": "telegram.delivery_started",
        "task_id": _task_id(self),
        "source_id": delivery.analysis.source_post.source_id,
        "x_post_id": delivery.analysis.source_post.external_id,
        "analysis_id": delivery.analysis_id,
        "delivery_target_id": delivery.target_id,
        "delivery_id": delivery.pk,
    }
    logger.info("Telegram delivery started.", extra=context)

    with delivery_send_lock(delivery.pk) as acquired:
        if not acquired:
            logger.info(
                "Telegram delivery skipped because the lock is held.",
                extra={
                    **context,
                    "event": "telegram.delivery_locked",
                    "status": "locked",
                },
            )
            return _result("locked", delivery)
        delivery = _load_delivery(analysis_id=analysis_id, target_id=target_id)
        if delivery is None:
            return {
                "status": "missing",
                "analysis_id": analysis_id,
                "target_id": target_id,
            }
        return _deliver_locked(task=self, delivery=delivery, context=context)


def _deliver_locked(
    *,
    task: Task,
    delivery: Delivery,
    context: dict[str, object],
) -> dict[str, int | str]:
    if delivery.status == DeliveryStatus.SENT:
        return _result("already_sent", delivery)
    if delivery.status == DeliveryStatus.FAILED:
        return _result("permanently_failed", delivery)
    if delivery.next_attempt_at and delivery.next_attempt_at > timezone.now():
        return _result("retry_scheduled", delivery)
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
        return _retry_or_fail(task=task, delivery=delivery, exc=exc, context=context)
    except TelegramPermanentChatError as exc:
        _mark_permanent_chat_failure(delivery.pk, str(exc))
        logger.error(
            "Telegram chat rejected the delivery.",
            extra={
                **context,
                "event": "telegram.delivery_failed",
                "status": "failed",
                "error_type": type(exc).__name__,
            },
        )
        return _result("failed", delivery)
    except _PERMANENT_DELIVERY_ERRORS as exc:
        _mark_failed(delivery.pk, str(exc))
        logger.error(
            "Telegram delivery failed permanently.",
            extra={
                **context,
                "event": "telegram.delivery_failed",
                "status": "failed",
                "error_type": type(exc).__name__,
            },
        )
        return _result("failed", delivery)

    _mark_sent(delivery.pk, message_id)
    logger.info(
        "Telegram delivery completed.",
        extra={
            **context,
            "event": "telegram.delivery_completed",
            "status": "sent",
        },
    )
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
    context: dict[str, object],
) -> dict[str, int | str]:
    configuration = SystemConfiguration.load()
    retries = getattr(task.request, "retries", 0)
    if retries < configuration.retry_count:
        countdown = exc.retry_after or min(
            _BASE_RETRY_SECONDS * (2**retries), _MAX_RETRY_SECONDS
        )
        _mark_retry_scheduled(delivery.pk, str(exc), countdown=countdown)
        logger.warning(
            "Temporary Telegram delivery failure; retry scheduled.",
            extra={
                **context,
                "event": "telegram.delivery_retry_scheduled",
                "status": "retry",
                "error_type": type(exc).__name__,
            },
        )
        raise task.retry(
            exc=exc,
            countdown=countdown,
            max_retries=configuration.retry_count,
        )
    _mark_failed(delivery.pk, str(exc))
    logger.error(
        "Telegram delivery retries exhausted.",
        extra={
            **context,
            "event": "telegram.delivery_retries_exhausted",
            "status": "failed",
            "error_type": type(exc).__name__,
        },
    )
    return _result("failed", delivery)


def _increment_attempts(delivery_id: int) -> None:
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


def _mark_sent(delivery_id: int, message_id: str) -> None:
    now = timezone.now()
    Delivery.objects.filter(pk=delivery_id).exclude(status=DeliveryStatus.SENT).update(
        status=DeliveryStatus.SENT,
        telegram_message_id=message_id,
        sent_at=now,
        next_attempt_at=None,
        updated_at=now,
        last_error="",
    )


def _mark_retry_scheduled(
    delivery_id: int,
    error: str,
    *,
    countdown: int,
) -> None:
    now = timezone.now()
    Delivery.objects.filter(
        pk=delivery_id,
        status=DeliveryStatus.PENDING,
    ).update(
        last_error=error,
        next_attempt_at=now + timedelta(seconds=countdown),
        updated_at=now,
    )


def _mark_failed(delivery_id: int, error: str) -> None:
    Delivery.objects.filter(pk=delivery_id).exclude(status=DeliveryStatus.SENT).update(
        status=DeliveryStatus.FAILED,
        last_error=error,
        next_attempt_at=None,
        updated_at=timezone.now(),
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
        delivery.next_attempt_at = None
        delivery.updated_at = timezone.now()
        delivery.save(
            update_fields=("status", "last_error", "next_attempt_at", "updated_at")
        )
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


def _task_id(task: Task) -> str:
    return str(getattr(task.request, "id", "") or "")
