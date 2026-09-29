"""Preserve quota posts when Telegram rejects optional custom emoji styling."""
import logging

from .client import TelegramPermanentChatError
from .models import Delivery


logger = logging.getLogger(__name__)


def send_with_emoji_fallback(client, delivery_id, kwargs):
    try:
        return client.send_message(**kwargs)
    except TelegramPermanentChatError:
        entities = kwargs.get("entities", [])
        if not any(entity["type"] == "custom_emoji" for entity in entities):
            raise
        fallback = [entity for entity in entities if entity["type"] != "custom_emoji"]
        Delivery.objects.filter(pk=delivery_id).update(message_entities=fallback)
        logger.warning("Telegram rejected custom emoji; sending regular emoji fallback.",
                       extra={"delivery_id": delivery_id})
        return client.send_message(**{**kwargs, "entities": fallback})
