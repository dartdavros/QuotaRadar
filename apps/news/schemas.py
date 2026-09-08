"""Strict structured output contracts; source text is always untrusted data."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class StrictPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Fact(StrictPayload):
    text: str = Field(min_length=1, max_length=700)
    evidence: str = Field(min_length=1, max_length=1500)


class AssessmentPayload(StrictPayload):
    relevant: bool
    product: str = Field(max_length=120)
    version: str = Field(max_length=180)
    event_type: Literal["model_release", "tool_release", "feature", "pricing", "limits", "practice", "incident", "other"]
    event_key: str = Field(max_length=200)
    confirmed: bool
    urgent: bool
    score: int = Field(ge=0, le=100)
    reason: str = Field(max_length=800)
    facts: list[Fact] = Field(max_length=12)
    related_event_id: int | None


class WritingPayload(StrictPayload):
    title: str = Field(min_length=1, max_length=160)
    text: str = Field(min_length=1, max_length=750)


class VerificationPayload(StrictPayload):
    supported: bool
    reason: str = Field(max_length=800)


class HistoricalVerificationPayload(VerificationPayload):
    still_relevant: bool = Field(description=(
        "Новость из истории сохраняет пользу на publication_time. False для прошедших акций, "
        "сбоев и объявлений, выданных за сегодняшние. Не домысливай текущую доступность."
    ))
