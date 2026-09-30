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
    # The provider truncates at maxLength, so the bounds sit far above the editorial norm:
    # a text that misses the norm has to be rewritten, never silently cut mid-word.
    title: str = Field(min_length=1, max_length=300, description=(
        "Заголовок новости на русском: одно законченное предложение длиной 40–90 символов. "
        "Называет суть одним фактом, не пересказывает новость целиком и не перечисляет "
        "подробности через запятую. Подробности идут в поле text, а не сюда."
    ))
    text: str = Field(min_length=1, max_length=1500, description=(
        "Текст новости на естественном русском языке. Объём определяется фактами: короткий "
        "источник не нужно растягивать. Обычно 2–3 коротких абзаца, разделённых пустой строкой. "
        "Первый абзац раскрывает заголовок без дословного повторения. Конкретные изменения, "
        "условия и ограничения из источников; без обращения к аудитории и обязательного вывода о пользе."
    ))


class VerificationPayload(StrictPayload):
    supported: bool
    reason: str = Field(max_length=800)


class HistoricalVerificationPayload(VerificationPayload):
    still_relevant: bool = Field(description=(
        "Новость из истории сохраняет пользу на publication_time. False для прошедших акций, "
        "сбоев и объявлений, выданных за сегодняшние. Не домысливай текущую доступность."
    ))


class EditorialVerificationPayload(VerificationPayload):
    editorial_quality: bool = Field(description=(
        "Текст готов к публикации: естественный русский язык, нет воды, повторов, "
        "рекламных оценок, обращения к аудитории и натянутого абзаца о пользе."
    ))


class HistoricalEditorialVerificationPayload(HistoricalVerificationPayload, EditorialVerificationPayload):
    pass
