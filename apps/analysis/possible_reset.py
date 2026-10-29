"""Group post for a suspected mass reset the LLM neither confirmed nor rejected."""

from __future__ import annotations

import logging

from apps.configuration.models import SystemConfiguration
from apps.monitoring.events import record_monitoring_event
from apps.monitoring.models import MonitoringComponent, MonitoringEventStatus
from apps.sources.models import SourcePost
from apps.telegram.services import queue_analysis_deliveries

from .fallback import agent_name
from .reassessment import SuspiciousIrrelevanceError
from .services import save_reset_warning_analysis

logger = logging.getLogger(__name__)

# Keeps the post, its date, link and advertising inside one Telegram message.
MAX_QUOTED_CHARACTERS = 1000


def possible_reset_title(agent: str) -> str:
    return f"{agent}: ВОЗМОЖНЫЙ СБРОС КВОТ"


def quote_author(text: str) -> str:
    """Quote the publication itself: nothing is classified or invented."""

    text = (text or "").strip()
    if len(text) > MAX_QUOTED_CHARACTERS:
        text = text[:MAX_QUOTED_CHARACTERS].rstrip() + "…"
    return f"«{text}»"


def deliver_possible_reset(
    *,
    source_post: SourcePost,
    configuration: SystemConfiguration,
    exc: SuspiciousIrrelevanceError,
    task_id: str = "",
) -> dict[str, int | str | bool]:
    """Publish the doubt to the group at once instead of parking the post."""

    analysis = save_reset_warning_analysis(
        source_post_id=source_post.pk,
        configuration=configuration,
        title=possible_reset_title(agent_name(source_post.source.provider)),
        message=quote_author(source_post.text),
        is_fallback=False,
        raw_response=exc.raw_response,
    )
    queued = queue_analysis_deliveries(analysis.pk)
    logger.warning(
        "Reset neither confirmed nor rejected; possible reset queued for the group.",
        extra={
            "event": "analysis.possible_reset",
            "task_id": task_id,
            "source_id": source_post.source_id,
            "x_post_id": source_post.external_id,
            "analysis_id": analysis.pk,
            "status": "possible_reset",
        },
    )
    record_monitoring_event(
        component=MonitoringComponent.AI,
        status=MonitoringEventStatus.ERROR,
        source=source_post.source,
        message=(
            f"{exc} По посту {source_post.external_id} в группу отправлен "
            f"«ВОЗМОЖНЫЙ СБРОС КВОТ»."
        ),
        error_type=type(exc).__name__,
        task_id=task_id,
    )
    return {
        "status": "possible_reset",
        "source_post_id": source_post.pk,
        "analysis_id": analysis.pk,
        "is_relevant": True,
        "queued_deliveries": len(queued.delivery_ids),
    }
