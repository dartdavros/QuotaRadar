"""Celery tasks for isolated, idempotent Telegram delivery."""

from __future__ import annotations

import logging

from celery import Task, shared_task
from django.utils import timezone

from apps.sources.models import Feed
from apps.monitoring.events import record_monitoring_event
from apps.monitoring.models import MonitoringComponent, MonitoringEventStatus

from .client import (
    TelegramAuthenticationError,
    TelegramBotApiClient,
    TelegramConfigurationError,
    TelegramPermanentChatError,
    TelegramResponseError,
    TelegramTemporaryError,
)
from .freshness import stale
from .delivery_state import (
    increment_attempts,
    mark_failed,
    mark_permanent_chat_failure,
    mark_sent,
)
from .locks import delivery_send_lock
from .models import Delivery, DeliveryStatus
from .services import DeliveryMessageError, format_delivery_message
from .task_support import _retry_or_fail, _result, _task_id
from apps.advertising.services import (
    begin_send, has_advertising, mark_uncertain, prepare_delivery, unconfirmed_send,
)

logger = logging.getLogger(__name__)


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
    if delivery.status == DeliveryStatus.UNCERTAIN or unconfirmed_send(delivery.pk):
        return _result("uncertain", delivery)
    if delivery.status == DeliveryStatus.FAILED:
        return _result("permanently_failed", delivery)
    if delivery.next_attempt_at and delivery.next_attempt_at > timezone.now():
        return _result("retry_scheduled", delivery)
    if not delivery.target.enabled or delivery.target.feed != Feed.QUOTA:
        mark_failed(delivery.pk, "Delivery target is disabled.")
        if delivery.target.is_private_chat:
            return _result("disabled", delivery)
        record_monitoring_event(
            component=MonitoringComponent.TELEGRAM,
            status=MonitoringEventStatus.ERROR,
            source=delivery.analysis.source_post.source,
            message=f"Доставка {delivery.pk} не выполнена: цель отключена.",
            error_type="DeliveryTargetDisabled",
            task_id=_task_id(task),
        )
        return _result("disabled", delivery)
    if stale(delivery.analysis.source_post.published_at, timezone.now()):
        mark_failed(delivery.pk, "Событие старше 30 минут.")
        record_monitoring_event(
            component=MonitoringComponent.TELEGRAM,
            status=MonitoringEventStatus.ERROR,
            source=delivery.analysis.source_post.source,
            message=f"Доставка {delivery.pk} отменена: событие старше 30 минут.",
            error_type="DeliveryStale",
            task_id=_task_id(task),
        )
        return _result("stale", delivery)

    try:
        text = delivery.rendered_text or format_delivery_message(delivery.analysis)
        text, entities = prepare_delivery(delivery, text)
    except (DeliveryMessageError, ValueError) as exc:
        mark_failed(delivery.pk, str(exc))
        record_monitoring_event(
            component=MonitoringComponent.TELEGRAM,
            status=MonitoringEventStatus.ERROR,
            source=delivery.analysis.source_post.source,
            message=f"Ошибка подготовки доставки {delivery.pk}: {exc}",
            error_type=type(exc).__name__,
            task_id=_task_id(task),
        )
        return _result("failed", delivery)

    increment_attempts(delivery.pk)
    try:
        with TelegramBotApiClient() as client:
            if not begin_send(delivery.pk):
                return _result("uncertain", delivery)
            kwargs = {"chat_id": delivery.target.telegram_chat_id, "text": text}
            if entities:
                kwargs["entities"] = entities
            message_id = client.send_message(**kwargs)
    except TelegramTemporaryError as exc:
        if has_advertising(delivery.pk) and exc.delivery_uncertain:
            mark_uncertain(delivery.pk, "Результат отправки неизвестен. Проверьте канал перед повтором.")
            return _result("uncertain", delivery)
        return _retry_or_fail(task=task, delivery=delivery, exc=exc, context=context)
    except TelegramPermanentChatError as exc:
        mark_permanent_chat_failure(delivery.pk, str(exc))
        if delivery.target.is_private_chat:
            logger.info(
                "Private chat rejected the delivery; subscription disabled.",
                extra={**context, "event": "telegram.subscriber_unreachable", "status": "failed"},
            )
            return _result("failed", delivery)
        logger.error(
            "Telegram chat rejected the delivery.",
            extra={
                **context,
                "event": "telegram.delivery_failed",
                "status": "failed",
                "error_type": type(exc).__name__,
            },
        )
        record_monitoring_event(
            component=MonitoringComponent.TELEGRAM,
            status=MonitoringEventStatus.ERROR,
            source=delivery.analysis.source_post.source,
            message=f"Ошибка доставки {delivery.pk}: {exc}",
            error_type=type(exc).__name__,
            task_id=_task_id(task),
        )
        return _result("failed", delivery)
    except _PERMANENT_DELIVERY_ERRORS as exc:
        if isinstance(exc, TelegramResponseError) and has_advertising(delivery.pk):
            mark_uncertain(delivery.pk, "Telegram не подтвердил отправку. Проверьте канал.")
            return _result("uncertain", delivery)
        mark_failed(delivery.pk, str(exc))
        logger.error(
            "Telegram delivery failed permanently.",
            extra={
                **context,
                "event": "telegram.delivery_failed",
                "status": "failed",
                "error_type": type(exc).__name__,
            },
        )
        record_monitoring_event(
            component=MonitoringComponent.TELEGRAM,
            status=MonitoringEventStatus.ERROR,
            source=delivery.analysis.source_post.source,
            message=f"Ошибка доставки {delivery.pk}: {exc}",
            error_type=type(exc).__name__,
            task_id=_task_id(task),
        )
        return _result("failed", delivery)

    mark_sent(delivery.pk, message_id)
    logger.info(
        "Telegram delivery completed.",
        extra={
            **context,
            "event": "telegram.delivery_completed",
            "status": "sent",
        },
    )
    record_monitoring_event(
        component=MonitoringComponent.TELEGRAM,
        status=MonitoringEventStatus.SUCCESS,
        source=delivery.analysis.source_post.source,
        message=f"Доставка {delivery.pk} успешно отправлена.",
        task_id=_task_id(task),
    )
    return _result("sent", delivery)


_PERMANENT_DELIVERY_ERRORS = (
    TelegramConfigurationError,
    TelegramAuthenticationError,
    TelegramResponseError,
)


def _load_delivery(*, analysis_id: int, target_id: int) -> Delivery | None:
    return (
        Delivery.objects.select_related(
            "analysis__source_post__source",
            "target",
        )
        .filter(analysis_id=analysis_id, target_id=target_id)
        .first()
    )
