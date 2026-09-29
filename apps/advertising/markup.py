"""Parse the small, explicit advertising markup into Telegram message entities."""
import re
from dataclasses import dataclass
from html import escape

from django.core.exceptions import ValidationError
from django.core.validators import URLValidator


_EMOJI = re.compile(r"(?P<emoji>[\U0001F300-\U0001FAFF])\[(?P<id>[0-9]{8,25})\]")
_BOLD_LINK = re.compile(r"\[\*\*(?P<label>[^\]\r\n*]+)\*\*\]\((?P<url>[^()\s]+)\)")
_LINK = re.compile(r"\[(?P<label>[^\]\r\n]+)\]\((?P<url>[^()\s]+)\)")
_BOLD = re.compile(r"\*\*(?P<label>[^*\r\n]+)\*\*")
_URL = URLValidator(schemes=("http", "https"))


def utf16_length(value):
    return len(value.encode("utf-16-le")) // 2


@dataclass(frozen=True)
class RenderedMarkup:
    text: str
    entities: list
    html: str


def render_markup(markup):
    """Keep links and emoji IDs out of the visible text and its length."""
    markup = markup.replace("\r\n", "\n")
    chunks, html, entities = [], [], []
    offset = 0
    position = 0
    while position < len(markup):
        match = next((found for expression in (_EMOJI, _BOLD_LINK, _LINK, _BOLD)
                      if (found := expression.match(markup, position))), None)
        if match:
            label = match.groupdict().get("label") or match.groupdict().get("emoji")
            length = utf16_length(label)
            if match.re is _EMOJI:
                entities.append({"type": "custom_emoji", "offset": offset,
                                 "length": length, "custom_emoji_id": match["id"]})
                html.append(f'<span title="ID {match["id"]}">{escape(label)}</span>')
            elif match.re in (_LINK, _BOLD_LINK):
                url = match["url"]
                try:
                    _URL(url)
                except ValidationError:
                    raise ValidationError("Ссылка должна содержать URL с http:// или https://.") from None
                if len(url) > 2000:
                    raise ValidationError("URL ссылки превышает 2000 символов.")
                entities.append({"type": "text_link", "offset": offset,
                                 "length": length, "url": url})
                if match.re is _BOLD_LINK:
                    entities.append({"type": "bold", "offset": offset, "length": length})
                contents = f"<strong>{escape(label)}</strong>" if match.re is _BOLD_LINK else escape(label)
                html.append(f'<a href="{escape(url, quote=True)}" target="_blank" rel="noopener noreferrer">{contents}</a>')
            else:
                entities.append({"type": "bold", "offset": offset, "length": length})
                html.append(f"<strong>{escape(label)}</strong>")
            chunks.append(label)
            offset += length
            position = match.end()
            continue
        character = markup[position]
        if character in "[]*" or character == "\r":
            raise ValidationError("Проверьте разметку: ссылку, жирный текст или код эмодзи.")
        chunks.append(character)
        html.append("<br>" if character == "\n" else escape(character))
        offset += utf16_length(character)
        position += 1
    result = "".join(chunks)
    if not result.strip():
        raise ValidationError("Введите текст рекомендации.")
    return RenderedMarkup(result, entities, "".join(html))
