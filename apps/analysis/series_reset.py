"""Approved Day N / Reset announcements have a deterministic classification."""

import re

from apps.sources.models import SourcePost

from .llm import LlmAnalysisResponse
from .reset_signals import (
    CODEX_RESET_AUTHOR_ID, has_reset_exclusions, is_verified_codex_reset_source,
)
from .schemas import AnalysisPayload

SERIES_RESET_MODEL = "rule/thsottiaux-day-reset-v1"
_DAY_LINE = re.compile(r"Day\s+([1-9][0-9]*)\s*/\s*Reset", re.IGNORECASE)
_CONTEXT_REQUIRING_ANALYSIS = re.compile(
    r"\b(?:cancelled|canceled|postponed|example|quote|quoted|tomorrow|will|scheduled|planned|landing|EOD)\b|```",
    re.IGNORECASE,
)


def classify_series_reset(post: SourcePost) -> LlmAnalysisResponse | None:
    """Read only standalone lines of the author's own text, never X includes."""

    if (
        not is_verified_codex_reset_source(post)
        or has_reset_exclusions(post.text)
        or _CONTEXT_REQUIRING_ANALYSIS.search(post.text)
    ):
        return None
    matches = [match for line in post.text.splitlines()
               if (match := _DAY_LINE.fullmatch(line.strip()))]
    if len(matches) != 1:
        return None
    day = matches[0].group(1)
    return LlmAnalysisResponse(
        payload=AnalysisPayload(
            is_relevant=True, event_type="quota_reset", provider="openai", product="codex",
            title_ru="🟢[CODEX] Использованные лимиты сброшены",
            message_ru=f"Объявлен сброс лимитов Codex — день {day}.",
        ),
        raw_response={"classification": {
            "method": "deterministic", "rule": SERIES_RESET_MODEL,
            "author_id": CODEX_RESET_AUTHOR_ID, "post_id": post.external_id, "day": day,
        }},
    )
