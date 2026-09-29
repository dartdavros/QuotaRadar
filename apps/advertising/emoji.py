"""Resolve custom emoji IDs with a read-only Bot API request; never publish."""
from django.core.cache import cache
from django.core.exceptions import ValidationError

from apps.telegram.client import TelegramApiError, TelegramBotApiClient


def resolve_emoji(emoji_id):
    key = f"advertising:emoji:{emoji_id}"
    fallback = cache.get(key)
    if fallback:
        return fallback
    try:
        with TelegramBotApiClient() as client:
            stickers = client.get_custom_emoji_stickers([emoji_id])
    except TelegramApiError:
        raise ValidationError(
            f"Не удалось получить эмодзи {emoji_id} из Telegram. "
            "Проверьте настройки токена бота, прокси и доступность Telegram; сообщения не отправлялись."
        ) from None
    fallback = next((item.get("emoji") for item in stickers
                     if item.get("custom_emoji_id") == emoji_id), None)
    if not fallback:
        raise ValidationError(f"Telegram не вернул эмодзи для ID {emoji_id}. Проверьте ID.")
    cache.set(key, fallback, timeout=60 * 60 * 24 * 7)
    return fallback
