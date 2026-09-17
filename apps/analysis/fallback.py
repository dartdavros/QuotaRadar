"""Keyword warning sent while the LLM is down, so a reset is not lost in silence."""

from __future__ import annotations

import logging
import re

from apps.configuration.models import SystemConfiguration
from apps.monitoring.events import record_monitoring_event
from apps.monitoring.models import MonitoringComponent, MonitoringEventStatus
from apps.sources.models import SourcePost, SourceProvider
from apps.telegram.services import queue_analysis_deliveries

from .availability import llm_unavailable
from .services import save_fallback_analysis

logger = logging.getLogger(__name__)

# The monitored accounts publish in English only; "reset" covers the past tense too.
RESET_PATTERN = re.compile(r"\breset(s|ting)?\b", re.IGNORECASE)

_AGENT_NAMES = {
    SourceProvider.OPENAI: "Codex",
    SourceProvider.ANTHROPIC: "Claude Code",
}


def mentions_reset(text: str) -> bool:
    """Report whether the author's own words announce a reset."""

    return bool(RESET_PATTERN.search(text or ""))


def agent_name(provider: str) -> str | None:
    """Return the agent shown to subscribers, or None for an unsupported provider."""

    return _AGENT_NAMES.get(provider)


def fallback_title(agent: str) -> str:
    return f"{agent}: возможный сброс лимитов"


def deliver_without_llm(
    *,
    source_post: SourcePost,
    configuration: SystemConfiguration,
    task_id: str = "",
) -> dict[str, int | str | bool] | None:
    """Queue the keyword warning, or return None when the fallback does not apply."""

    if not llm_unavailable():
        return None
    agent = agent_name(source_post.source.provider)
    if agent is None or not mentions_reset(source_post.text):
        return None

    analysis = save_fallback_analysis(
        source_post_id=source_post.pk,
        configuration=configuration,
        title=fallback_title(agent),
    )
    if analysis.is_fallback is not True:
        # Another worker already stored a real analysis for this post.
        return None

    queued = queue_analysis_deliveries(analysis.pk)
    logger.warning(
        "LLM is unavailable; keyword warning queued instead of an analysis.",
        extra={
            "event": "analysis.keyword_fallback",
            "task_id": task_id,
            "source_id": source_post.source_id,
            "x_post_id": source_post.external_id,
            "analysis_id": analysis.pk,
            "status": "fallback",
        },
    )
    record_monitoring_event(
        component=MonitoringComponent.AI,
        status=MonitoringEventStatus.ERROR,
        source=source_post.source,
        message=(
            f"LLM недоступна: по посту {source_post.external_id} отправлено "
            f"предупреждение по ключевому слову вместо анализа."
        ),
        error_type="LlmUnavailableFallback",
        task_id=task_id,
    )
    return {
        "status": "fallback",
        "source_post_id": source_post.pk,
        "analysis_id": analysis.pk,
        "is_relevant": True,
        "queued_deliveries": len(queued.delivery_ids),
    }
