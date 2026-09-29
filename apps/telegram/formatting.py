"""Application-owned Telegram text rendering and UTF-16 limits."""
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from django.utils import timezone
from apps.configuration.models import SystemConfiguration
from apps.analysis.models import Analysis
from apps.advertising.formatting import utf16_length

TELEGRAM_MESSAGE_LIMIT = 4096
_RUSSIAN_MONTHS = (
    "января",
    "февраля",
    "марта",
    "апреля",
    "мая",
    "июня",
    "июля",
    "августа",
    "сентября",
    "октября",
    "ноября",
    "декабря",
)
_TIMEZONE_LABELS = {"Europe/Moscow": "МСК"}


class DeliveryMessageError(ValueError):
    """An analysis cannot be represented as a valid Telegram message."""


def format_delivery_message(analysis: Analysis) -> str:
    if analysis.is_relevant is not True:
        raise DeliveryMessageError("Only relevant analyses can be delivered.")
    if analysis.is_fallback:
        return _format_fallback_message(analysis)
    return format_message_values(analysis.title_ru, analysis.message_ru, analysis.source_post)


def format_message_values(title, message, post):
    title, message, source_url = title.strip(), message.strip(), post.source_url.strip()
    if not title or not message or not source_url:
        raise DeliveryMessageError("Relevant analysis is missing delivery content.")
    configuration = SystemConfiguration.load()
    published_at = _format_publication_date(
        post.published_at,
        configuration.telegram_message_timezone,
    )
    payload = (
        f"{title}\n\n{message}\n\n"
        f"Опубликовано: {published_at}\n"
        f"Источник: {source_url}"
    )
    if utf16_length(payload) > TELEGRAM_MESSAGE_LIMIT:
        raise DeliveryMessageError("Telegram message is too long (exceeds 4096 characters).")
    return payload


def _format_fallback_message(analysis: Analysis) -> str:
    """The LLM was down: the agent, the suspicion and the post, nothing invented."""

    title = analysis.title_ru.strip()
    source_url = analysis.source_post.source_url.strip()
    if not title or not source_url:
        raise DeliveryMessageError("Keyword warning is missing delivery content.")
    return f"{title}\n{source_url}"


def _format_publication_date(value: datetime, timezone_name: str) -> str:
    try:
        target_timezone = ZoneInfo(timezone_name)
    except (TypeError, ValueError, ZoneInfoNotFoundError):
        raise DeliveryMessageError(
            "Telegram publication timezone is invalid."
        ) from None

    local_value = timezone.localtime(value, target_timezone)
    timezone_label = (
        _TIMEZONE_LABELS.get(timezone_name) or local_value.tzname() or timezone_name
    )
    month = _RUSSIAN_MONTHS[local_value.month - 1]
    return (
        f"{local_value.day} {month} {local_value.year}, "
        f"{local_value:%H:%M} {timezone_label}"
    )
