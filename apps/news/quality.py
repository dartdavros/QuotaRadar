"""Deterministic evidence checks and publication rendering."""
from html import escape
import re

from .schemas import AssessmentPayload, WritingPayload
from .errors import NewsPolicyError

TITLE_LIMIT = 120
TEXT_FLOOR = 200


def validate_assessment(payload: AssessmentPayload, post):
    if not payload.relevant:
        return
    if not payload.confirmed or not payload.facts or not payload.product.strip() or not payload.event_key.strip():
        raise NewsPolicyError("Не хватает подтверждённых фактов события.")
    normalized = " ".join(post.normalized_text.split())
    for fact in payload.facts:
        if " ".join(fact.evidence.split()) not in normalized:
            raise NewsPolicyError("Подтверждающий фрагмент отсутствует в источнике.")
    if payload.urgent and payload.event_type not in {"model_release", "tool_release"}:
        raise NewsPolicyError("Срочность разрешена только подтверждённому крупному запуску.")


def tidy(value):
    return " ".join(value.split())


def editorial(writing: WritingPayload):
    """A deterministic floor under the model: the writing prompt asks for exactly this."""
    title, text = tidy(writing.title), tidy(writing.text)
    if len(title) > TITLE_LIMIT:
        raise NewsPolicyError("Заголовок длиннее допустимого и, вероятно, обрезан.")
    if len(text) < TEXT_FLOOR:
        raise NewsPolicyError("Текст новости короче допустимого.")
    if text.casefold().startswith(title.casefold()):
        raise NewsPolicyError("Текст повторяет заголовок первой строкой.")


def render(writing: WritingPayload, posts):
    editorial(writing)
    for value in (writing.title, writing.text):
        if not re.search("[А-Яа-яЁё]", value):
            raise NewsPolicyError("Новость должна быть на русском языке.")
        if re.search(r"https?://|www\.", value):
            raise NewsPolicyError("Ссылки добавляются из источников, не из ответа ИИ.")
    links = " · ".join(f'<a href="{escape(p.source_url, quote=True)}">@{escape(p.source.username)}</a>' for p in posts)
    text = f"<b>{escape(writing.title)}</b>\n\n{escape(writing.text)}\n\n{links}"
    # Telegram counts UTF-16 text units after entity parsing.
    visible = f"{writing.title}\n\n{writing.text}\n\n" + " · ".join("@"+p.source.username for p in posts)
    if len(visible.encode("utf-16-le")) // 2 > 1024:
        raise NewsPolicyError("Подпись с источниками превышает лимит Telegram.")
    return text
