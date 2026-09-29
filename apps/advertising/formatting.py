"""Advertising copy and UTF-16 space accounting."""
import re

from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from .markup import render_markup, utf16_length

AD_SEPARATOR = "\n\n"
MESSAGE_LIMIT = 4096
PREFIX = "Рекомендация: "


def advertising_text(message, link_label):
    return f"{PREFIX}{message.strip()} {link_label.strip()}"


def campaign_copy(campaign):
    if campaign.body:
        rendered = render_markup(campaign.body.strip(), emoji_fallbacks=campaign.emoji_fallbacks)
        return PREFIX.rstrip() + "\n" + rendered.text, rendered.entities
    block = advertising_text(campaign.message, campaign.link_label)
    return block, [{"type": "text_link", "offset": utf16_length(PREFIX + campaign.message.strip() + " "),
                    "length": utf16_length(campaign.link_label.strip()), "url": campaign.url}]


def validate_body(body, *, emoji_fallbacks=None):
    rendered = render_markup(body.strip(), emoji_fallbacks=emoji_fallbacks)
    block = PREFIX.rstrip() + "\n" + rendered.text
    if utf16_length(block) > MESSAGE_LIMIT:
        raise ValidationError("Текст превышает лимит Telegram — 4096 единиц UTF-16 после разбора разметки.")
    return rendered


def validate_copy(message, link_label, url):
    for field, value in (("message", message), ("link_label", link_label)):
        if not value.strip() or any(character in value for character in "\r\n"):
            raise ValidationError({field: "Введите непустой текст в одну строку."})
        if re.search(r"https?://|www\.", value, re.IGNORECASE):
            raise ValidationError({field: "Ссылку укажите в отдельном поле URL."})
    URLValidator(schemes=("http", "https"))(url)
    if utf16_length(advertising_text(message, link_label)) > MESSAGE_LIMIT:
        raise ValidationError({"message": "Текст превышает лимит Telegram — 4096 единиц UTF-16."})


def append_advertising(post, campaign, source_url=""):
    block, ad_entities = campaign_copy(campaign)
    if utf16_length(post + AD_SEPARATOR + block) > MESSAGE_LIMIT:
        raise ValueError("Пост вместе с рекомендацией превышает лимит Telegram — 4096 единиц UTF-16. Текст не обрезан.")
    offset = utf16_length(post + AD_SEPARATOR)
    entities = []
    source_offset = post.rfind(source_url) if source_url else -1
    if source_offset >= 0:
        entities.append({"type": "url", "offset": utf16_length(post[:source_offset]),
                         "length": utf16_length(source_url)})
    if campaign.body:
        offset += utf16_length(PREFIX.rstrip() + "\n")
    entities.extend({**entity, "offset": entity["offset"] + offset} for entity in ad_entities)
    return post + AD_SEPARATOR + block, entities
