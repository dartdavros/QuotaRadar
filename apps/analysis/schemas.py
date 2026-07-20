"""Strict structured-output schema returned by the configured LLM."""

from __future__ import annotations

from typing import Annotated, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    StringConstraints,
    field_validator,
    model_validator,
)

EventType = Literal["quota_reset", "quota_increase", "quota_extension"]
Provider = Literal["openai", "anthropic"]
Product = Literal["codex", "claude_code"]
Title = Annotated[str, StringConstraints(max_length=255)]


class AnalysisPayload(BaseModel):
    """Server-side contract for a single quota-event classification."""

    model_config = ConfigDict(extra="forbid", strict=True)

    is_relevant: bool
    event_type: EventType | None
    provider: Provider
    product: Product
    title_ru: Title | None
    message_ru: str | None

    @field_validator("title_ru", "message_ru")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @model_validator(mode="after")
    def validate_relevance_shape(self) -> Self:
        if self.is_relevant:
            missing = [
                name
                for name, value in (
                    ("event_type", self.event_type),
                    ("title_ru", self.title_ru),
                    ("message_ru", self.message_ru),
                )
                if value is None
            ]
            if missing:
                raise ValueError(
                    "Relevant output requires event_type, title_ru and message_ru."
                )
        elif any((self.event_type, self.title_ru, self.message_ru)):
            raise ValueError(
                "Irrelevant output requires null event_type, title_ru and message_ru."
            )
        return self


def structured_output_json_schema() -> dict[str, object]:
    """Return the strict JSON schema sent to OpenAI-compatible endpoints."""

    schema = AnalysisPayload.model_json_schema()
    schema["additionalProperties"] = False
    return schema
