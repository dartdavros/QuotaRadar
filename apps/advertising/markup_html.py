"""Telegram HTML tags converted into text/entities; input HTML is never served."""
from html.parser import HTMLParser

from django.core.exceptions import ValidationError

from .markup_result import link_entity


_TAGS = {"b": "bold", "strong": "bold", "i": "italic", "em": "italic",
         "u": "underline", "ins": "underline", "s": "strikethrough",
         "strike": "strikethrough", "del": "strikethrough", "span": "spoiler",
         "tg-spoiler": "spoiler", "a": "text_link", "tg-emoji": "custom_emoji",
         "code": "code", "pre": "pre", "blockquote": "blockquote", "tg-time": "date_time"}


class TelegramHTMLParser(HTMLParser):
    def __init__(self, builder):
        super().__init__(convert_charrefs=True)
        self.builder = builder
        self.stack = []

    def parse(self, text):
        self.feed(text)
        self.close()
        if self.stack:
            raise ValidationError(f"Не закрыт тег <{self.stack[-1][0]}>.")

    def handle_starttag(self, tag, attributes):
        attributes = dict(attributes)
        if tag == "br":
            self.builder.add("\n")
            return
        kind = _TAGS.get(tag)
        if not kind:
            raise ValidationError(f"Тег <{tag}> не поддерживается в текстовых сообщениях Telegram.")
        extra = {}
        if tag == "span" and attributes.get("class") != "tg-spoiler":
            raise ValidationError('Telegram поддерживает только <span class="tg-spoiler">.')
        if tag == "a":
            kind, extra = link_entity(attributes.get("href", ""))
        elif tag == "tg-emoji":
            kind, extra = link_entity(f'tg://emoji?id={attributes.get("emoji-id", "")}', image=True)
        elif tag == "tg-time":
            kind, extra = link_entity(
                f'tg://time?unix={attributes.get("unix", "")}&format={attributes.get("format", "")}', image=True)
        elif tag == "blockquote" and "expandable" in attributes:
            kind = "expandable_blockquote"
        elif tag == "code" and self.stack and self.stack[-1][1] == "pre":
            language = attributes.get("class", "")
            if language.startswith("language-"):
                self.stack[-1][3]["language"] = language[len("language-"):]
            kind = None
        if len(self.stack) > 64:
            raise ValidationError("Слишком глубокая вложенность разметки.")
        self.stack.append((tag, kind, self.builder.offset, extra))

    def handle_endtag(self, tag):
        if not self.stack or self.stack[-1][0] != tag:
            raise ValidationError(f"Проверьте порядок закрытия тега </{tag}>.")
        _, kind, start, extra = self.stack.pop()
        if kind == "custom_emoji":
            contents = "".join(self.builder.chunks).encode("utf-16-le")[start * 2:].decode("utf-16-le")
            from .markup_result import EMOJI_SEQUENCE
            if not EMOJI_SEQUENCE.fullmatch(contents):
                raise ValidationError("Внутри <tg-emoji> нужен обычный эмодзи.")
            self.builder.used_fallbacks[extra["custom_emoji_id"]] = contents
        if kind:
            self.builder.entity(kind, start, **extra)

    def handle_data(self, data):
        if any(item[0] in {"pre", "code", "tg-emoji"} for item in self.stack):
            self.builder.add(data)
        else:
            self.builder.add_with_ids(data)

    def handle_comment(self, data):
        raise ValidationError("Комментарии HTML не поддерживаются Telegram.")
