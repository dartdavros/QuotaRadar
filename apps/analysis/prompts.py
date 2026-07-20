"""Prompt rendering from versioned database configuration."""

from __future__ import annotations

from dataclasses import dataclass

from apps.configuration.models import SystemConfiguration
from apps.sources.models import SourcePost

from .quality import expected_product


class PromptConfigurationError(RuntimeError):
    """Raised when the active prompt cannot be safely rendered."""


@dataclass(frozen=True, slots=True)
class RenderedPrompt:
    system_prompt: str
    user_prompt: str
    version: int


def render_prompt(
    *,
    source_post: SourcePost,
    configuration: SystemConfiguration,
) -> RenderedPrompt:
    prompt = configuration.active_prompt
    if not prompt.is_active:
        raise PromptConfigurationError("The configured prompt is inactive.")
    values = {
        "source": f"@{source_post.source.username}",
        "expected_product": expected_product(source_post.source.provider),
        "published_at": source_post.published_at.isoformat(),
        "source_url": source_post.source_url,
        "normalized_text": source_post.normalized_text,
    }
    try:
        user_prompt = prompt.user_prompt_template.format_map(values)
    except (KeyError, ValueError):
        raise PromptConfigurationError(
            "The configured user prompt template is invalid."
        ) from None
    if not prompt.system_prompt.strip() or not user_prompt.strip():
        raise PromptConfigurationError("The configured prompt is empty.")
    return RenderedPrompt(
        system_prompt=prompt.system_prompt.strip(),
        user_prompt=user_prompt.strip(),
        version=prompt.version,
    )
