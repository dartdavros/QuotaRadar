"""Shared text/entity builder and safe browser preview of those same entities."""
import re
from dataclasses import dataclass
from html import escape
from urllib.parse import parse_qs, urlsplit

from django.core.exceptions import ValidationError

from .emoji import resolve_emoji


EMOJI_ID = re.compile(r"\[([0-9]+)\]")
EMOJI_CHARACTER = r"[\U0001F000-\U0001FAFF\u2190-\u27BF\u2934\u2935\u2B00-\u2BFF\u00A9\u00AE\u203C\u2049\u2122\u2139\u3030\u303D\u3297\u3299]"
EMOJI_SEQUENCE = re.compile(
    rf"(?:{EMOJI_CHARACTER}(?:[\ufe0f\ufe0e\U0001F3FB-\U0001F3FF]|\u200d{EMOJI_CHARACTER})*|[0-9#*]\ufe0f?\u20e3)+"
)
LEGACY_EMOJI = re.compile(rf"(?P<emoji>{EMOJI_SEQUENCE.pattern})\[(?P<id>[0-9]+)\]")
_STYLES = {"bold", "italic", "underline", "strikethrough", "spoiler"}


def utf16_length(value):
    return len(value.encode("utf-16-le")) // 2


def link_entity(url, *, image=False):
    try:
        parts = urlsplit(url)
    except ValueError:
        raise ValidationError("Проверьте адрес ссылки.") from None
    if parts.scheme.lower() not in {"http", "https", "tg", "mailto", "tel"} or any(c in url for c in '\r\n\t<>"'):
        raise ValidationError("Ссылка должна содержать URL Telegram, HTTP/HTTPS, mailto: или tel:.")
    if parts.scheme in {"http", "https", "tg"} and not parts.netloc:
        raise ValidationError("В ссылке отсутствует адрес.")
    query = parse_qs(parts.query)
    if image and parts.scheme == "tg" and parts.netloc == "emoji":
        emoji_id = query.get("id", [""])[0]
        if not emoji_id.isdigit() or int(emoji_id) <= 0:
            raise ValidationError("Код кастомного эмодзи должен быть положительным числом.")
        return "custom_emoji", {"custom_emoji_id": emoji_id}
    if image and parts.scheme == "tg" and parts.netloc == "time":
        unix = query.get("unix", [""])[0]
        format_ = query.get("format", [""])[0]
        if not unix.isdigit() or not re.fullmatch(r"r|w?[dD]?[tT]?", format_):
            raise ValidationError("Проверьте unix и format в разметке даты Telegram.")
        return "date_time", {"unix_time": int(unix), "date_time_format": format_}
    if image:
        raise ValidationError("В текстовом сообщении ![...] поддерживает tg://emoji и tg://time.")
    return "text_link", {"url": url}


@dataclass(frozen=True)
class RenderedMarkup:
    text: str
    entities: list
    html: str
    emoji_fallbacks: dict


class MarkupBuilder:
    def __init__(self, emoji_fallbacks=None):
        self.chunks = []
        self.entities = []
        self.offset = 0
        self.fallbacks = dict(emoji_fallbacks or {})
        self.used_fallbacks = {}

    def add(self, text):
        self.chunks.append(text)
        self.offset += utf16_length(text)

    def entity(self, kind, start, **attributes):
        if self.offset > start:
            self.entities.append({"type": kind, "offset": start,
                                  "length": self.offset - start, **attributes})

    def emoji(self, emoji_id, fallback=None):
        if not emoji_id.isdigit() or int(emoji_id) <= 0:
            raise ValidationError("Код кастомного эмодзи должен быть положительным числом.")
        fallback = fallback or self.fallbacks.get(emoji_id) or resolve_emoji(emoji_id)
        if not EMOJI_SEQUENCE.fullmatch(fallback):
            raise ValidationError(f"Для эмодзи {emoji_id} нужен обычный эмодзи в качестве запасного отображения.")
        start = self.offset
        self.add(fallback)
        self.entity("custom_emoji", start, custom_emoji_id=emoji_id)
        self.used_fallbacks[emoji_id] = fallback

    def add_with_ids(self, value):
        position = 0
        for match in re.finditer(rf"{LEGACY_EMOJI.pattern}|{EMOJI_ID.pattern}", value):
            self.add(value[position:match.start()])
            self.emoji(match.group("id") or match[3], match.group("emoji"))
            position = match.end()
        self.add(value[position:])

    def finish(self):
        text = "".join(self.chunks)
        entities = sorted(self.entities, key=lambda item: (item["offset"], -item["length"], item["type"] != "text_link"))
        validate_entities(entities)
        return RenderedMarkup(text, entities, preview_html(text, entities), self.used_fallbacks)


def validate_entities(entities):
    for index, outer in enumerate(entities):
        end = outer["offset"] + outer["length"]
        for inner in entities[index + 1:]:
            if inner["offset"] >= end:
                break
            if inner["offset"] + inner["length"] > end:
                raise ValidationError("Оформление пересекается: вложенные выделения должны закрываться по порядку.")
            types = {outer["type"], inner["type"]}
            quotes = {"blockquote", "expandable_blockquote"}
            if (types & {"code", "pre"} or outer["type"] in quotes and inner["type"] in quotes
                    or not types & (_STYLES | quotes)):
                raise ValidationError("Такое вложение форматирования не поддерживается Telegram.")


def preview_html(text, entities):
    tags = {"bold": ("<strong>", "</strong>"), "italic": ("<em>", "</em>"),
            "underline": ("<u>", "</u>"), "strikethrough": ("<s>", "</s>"),
            "spoiler": ('<span class="tg-spoiler">', "</span>"),
            "code": ("<code>", "</code>"), "pre": ("<pre><code>", "</code></pre>"),
            "blockquote": ("<blockquote>", "</blockquote>"),
            "expandable_blockquote": ("<blockquote expandable>", "</blockquote>")}
    opens, closes = {}, {}
    for entity in entities:
        kind = entity["type"]
        opening, closing = tags.get(kind, ("", ""))
        if kind == "text_link":
            url = escape(entity["url"], quote=True)
            opening, closing = f'<a href="{url}" target="_blank" rel="noopener noreferrer">', "</a>"
        elif kind == "custom_emoji":
            opening, closing = f'<span title="ID {entity["custom_emoji_id"]}">', "</span>"
        elif kind == "date_time":
            opening, closing = f'<time data-unix="{entity["unix_time"]}">', "</time>"
        opens.setdefault(entity["offset"], []).append(opening)
        closes.setdefault(entity["offset"] + entity["length"], []).insert(0, closing)
    result, offset = [], 0
    for character in text:
        result.extend(closes.get(offset, []))
        result.extend(opens.get(offset, []))
        result.append("<br>" if character == "\n" else escape(character))
        offset += utf16_length(character)
    result.extend(closes.get(offset, []))
    return "".join(result)
