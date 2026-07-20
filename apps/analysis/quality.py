"""Application-owned quality checks and final notification formatting."""

from __future__ import annotations

import re

from apps.sources.models import SourcePost, SourceProvider

from .models import Analysis, AnalysisProduct
from .schemas import AnalysisPayload

TELEGRAM_MESSAGE_MAX_LENGTH = 4096
TITLE_MAX_LENGTH = 255
_CYRILLIC_PATTERN = re.compile(r"[А-Яа-яЁё]")
_URL_PATTERN = re.compile(
    r"(?:https?://|www\.|\b[a-z0-9](?:[a-z0-9-]*[a-z0-9])?"
    r"(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)*\.[a-z]{2,63}\b)",
    re.IGNORECASE,
)


class AnalysisQualityError(ValueError):
    """Raised when valid JSON violates QuotaRadar domain constraints."""


def expected_product(provider: str) -> str:
    mapping = {
        SourceProvider.OPENAI: AnalysisProduct.CODEX,
        SourceProvider.ANTHROPIC: AnalysisProduct.CLAUDE_CODE,
    }
    try:
        return mapping[provider]
    except KeyError:
        raise AnalysisQualityError(
            "Source provider is not supported for analysis."
        ) from None


def validate_payload_for_post(
    *,
    payload: AnalysisPayload,
    source_post: SourcePost,
) -> None:
    """Validate source identity, Russian copy, links and Telegram size."""

    expected_provider = source_post.source.provider
    product = expected_product(expected_provider)
    if payload.provider != expected_provider or payload.product != product:
        raise AnalysisQualityError(
            "LLM output provider or product does not match the source."
        )
    if not payload.is_relevant:
        return

    title = payload.title_ru or ""
    message = payload.message_ru or ""
    if len(title) > TITLE_MAX_LENGTH:
        raise AnalysisQualityError("Relevant title is too long.")
    if not _CYRILLIC_PATTERN.search(title) or not _CYRILLIC_PATTERN.search(message):
        raise AnalysisQualityError("Relevant title and message must be in Russian.")
    if _URL_PATTERN.search(title) or _URL_PATTERN.search(message):
        raise AnalysisQualityError("LLM output must not contain links.")

    rendered = build_notification_text_values(
        title_ru=title,
        message_ru=message,
        source_url=source_post.source_url,
    )
    if len(rendered) > TELEGRAM_MESSAGE_MAX_LENGTH:
        raise AnalysisQualityError("Rendered Telegram message is too long.")


def build_notification_text_values(
    *,
    title_ru: str,
    message_ru: str,
    source_url: str,
) -> str:
    """Add the trusted X source URL outside the LLM response."""

    return f"{title_ru.strip()}\n\n{message_ru.strip()}\n\nИсточник: {source_url}"


def build_notification_text(analysis: Analysis) -> str:
    """Render a validated relevant analysis for the Telegram delivery stage."""

    if not analysis.is_successful or analysis.is_relevant is not True:
        raise AnalysisQualityError(
            "Only a successful relevant analysis can be rendered for delivery."
        )
    return build_notification_text_values(
        title_ru=analysis.title_ru,
        message_ru=analysis.message_ru,
        source_url=analysis.source_post.source_url,
    )
