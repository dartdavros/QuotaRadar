"""Retry policy and compact results for Telegram Celery tasks."""
import logging
from celery import Task
from apps.configuration.models import SystemConfiguration
from apps.monitoring.events import record_monitoring_event
from apps.monitoring.models import MonitoringComponent, MonitoringEventStatus
from .client import TelegramTemporaryError
from .delivery_state import mark_failed, mark_retry_scheduled
from .models import Delivery

logger = logging.getLogger(__name__)
_BASE_RETRY_SECONDS = 30
_MAX_RETRY_SECONDS = 900

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
        mark_retry_scheduled(delivery.pk, str(exc), countdown=countdown)
        record_monitoring_event(
            component=MonitoringComponent.TELEGRAM,
            status=MonitoringEventStatus.ERROR,
            source=delivery.analysis.source_post.source,
            message=(
                f"Временная ошибка доставки {delivery.pk}: {exc}. "
                f"Повтор через {countdown} сек."
            ),
            error_type=type(exc).__name__,
            task_id=_task_id(task),
        )
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
    mark_failed(delivery.pk, str(exc))
    logger.error(
        "Telegram delivery retries exhausted.",
        extra={
            **context,
            "event": "telegram.delivery_retries_exhausted",
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


def _result(status: str, delivery: Delivery) -> dict[str, int | str]:
    return {
        "status": status,
        "delivery_id": delivery.pk,
        "analysis_id": delivery.analysis_id,
        "target_id": delivery.target_id,
    }


def _task_id(task: Task) -> str:
    return str(getattr(task.request, "id", "") or "")
