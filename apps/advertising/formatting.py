"""Plain advertising copy with exactly one explicitly marked text link."""
import re

from django.core.exceptions import ValidationError
from django.core.validators import URLValidator

AD_LIMIT = 200
AD_SEPARATOR = "\n\n"
MESSAGE_LIMIT = 4096
PREFIX = "Рекомендация: "


def utf16_length(text):
    return len(text.encode("utf-16-le")) // 2


def advertising_text(message, link_label):
    return f"{PREFIX}{message.strip()} {link_label.strip()}"


def validate_copy(message, link_label, url):
    for field, value in (("message", message), ("link_label", link_label)):
        if not value.strip() or any(character in value for character in "\r\n"):
            raise ValidationError({field: "Введите непустой текст в одну строку."})
        if re.search(r"https?://|www\.", value, re.IGNORECASE):
            raise ValidationError({field: "Ссылку укажите в отдельном поле URL."})
    URLValidator(schemes=("http", "https"))(url)
    if utf16_length(advertising_text(message, link_label)) > AD_LIMIT:
        raise ValidationError({"message": "Рекламный блок превышает 200 единиц UTF-16, включая «Рекомендация: » и текст ссылки."})


def append_advertising(post, campaign, source_url=""):
    block = advertising_text(campaign.message, campaign.link_label)
    # Always reserve the entire agreed advertising allowance, never truncate copy.
    if utf16_length(post) + utf16_length(AD_SEPARATOR) + AD_LIMIT > MESSAGE_LIMIT:
        raise ValueError("В посте недостаточно места для рекламного блока: максимум основного поста — 3894 единицы UTF-16.")
    offset = utf16_length(post + AD_SEPARATOR + PREFIX + campaign.message.strip() + " ")
    entities = []
    source_offset = post.rfind(source_url) if source_url else -1
    if source_offset >= 0:
        entities.append({"type": "url", "offset": utf16_length(post[:source_offset]),
                         "length": utf16_length(source_url)})
    entities.append({"type": "text_link", "offset": offset,
                     "length": utf16_length(campaign.link_label.strip()), "url": campaign.url})
    return post + AD_SEPARATOR + block, entities
