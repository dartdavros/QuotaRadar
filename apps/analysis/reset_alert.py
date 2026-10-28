"""Owner heads-up when a suspected mass reset was neither confirmed nor rejected."""

from __future__ import annotations

import logging

from apps.configuration.models import SystemConfiguration
from apps.monitoring.events import record_monitoring_event
from apps.monitoring.models import MonitoringComponent, MonitoringEventStatus
from apps.sources.models import SourcePost
from apps.telegram.client import TelegramApiError, TelegramBotApiClient

logger = logging.getLogger(__name__)

MAX_QUOTED_CHARACTERS = 280


def build_alert_text(source_post: SourcePost) -> str:
    """Quote the publication itself: the owner decides, the application does not classify."""

    text = (source_post.text or "").strip()
    if len(text) > MAX_QUOTED_CHARACTERS:
        text = text[:MAX_QUOTED_CHARACTERS].rstrip() + "…"
    return (
        "⚠️ Требуется проверка: сброс квоты не подтверждён и не отклонён.\n"
        f"Источник: @{source_post.source.username}\n"
        f"Ссылка: {source_post.source_url}\n\n"
        f"{text}"
    )


def send_reset_review_alert(
    *,
    source_post: SourcePost,
    configuration: SystemConfiguration,
    task_id: str = "",
) -> bool:
    """Send one service message, or do nothing while no alert chat is configured."""

    chat_id = configuration.reset_alert_chat_id.strip()
    if not chat_id:
        return False
    try:
        with TelegramBotApiClient() as client:
            client.send_message(chat_id=chat_id, text=build_alert_text(source_post))
    except TelegramApiError as exc:
        record_monitoring_event(
            component=MonitoringComponent.TELEGRAM,
            status=MonitoringEventStatus.ERROR,
            source=source_post.source,
            message=f"Сигнал о неподтверждённом сбросе не отправлен: {exc}",
            error_type=type(exc).__name__,
            task_id=task_id,
        )
        logger.warning(
            "Reset review alert could not be delivered.",
            extra={
                "event": "analysis.reset_alert_failed",
                "x_post_id": source_post.external_id,
                "status": "failed",
            },
        )
        return False
    record_monitoring_event(
        component=MonitoringComponent.TELEGRAM,
        status=MonitoringEventStatus.SUCCESS,
        source=source_post.source,
        message=f"Отправлен сигнал о неподтверждённом сбросе: пост {source_post.external_id}.",
        task_id=task_id,
    )
    return True
