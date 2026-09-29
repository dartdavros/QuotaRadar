"""Telegram MarkdownV2 text entities, with **bold** and [ID] editor shortcuts."""
import re

from django.core.exceptions import ValidationError

from .markup_result import EMOJI_ID, LEGACY_EMOJI, link_entity


_FORMATS = (("**", "bold"), ("__", "underline"), ("||", "spoiler"),
            ("~~", "strikethrough"), ("*", "bold"), ("_", "italic"), ("~", "strikethrough"))
_PLAIN_URL = re.compile(r"(?:https?://|tg://|mailto:|tel:)[^\s<>]+")


def unescape(value):
    return re.sub(r"\\([\x01-\x7e])", r"\1", value)


def closing_position(text, marker, start):
    position = start
    while position < len(text):
        if text[position] == "\\":
            position += 2
            continue
        if len(marker) == 1 and marker in "*_~" and text.startswith(marker * 2, position):
            position += 2
            continue
        if text.startswith(marker, position):
            return position
        if marker not in {"`", "```"}:
            link = read_link(text, position)
            if link:
                position = link[2]
                continue
            if text[position] == "`":
                code_marker = "```" if text.startswith("```", position) else "`"
                end = closing_position(text, code_marker, position + len(code_marker))
                if end >= 0:
                    position = end + len(code_marker)
                    continue
        position += 1
    return -1


def read_link(text, start):
    """Balanced labels and destinations; escaped parentheses stay in the URL."""
    image = text.startswith("![", start)
    left = start + int(image)
    if not text.startswith("[", left):
        return None
    cursor, depth = left + 1, 1
    while cursor < len(text) and depth:
        if text[cursor] == "\\":
            cursor += 2
            continue
        depth += (text[cursor] == "[") - (text[cursor] == "]")
        cursor += 1
    if depth or not text.startswith("(", cursor):
        return None
    label = text[left + 1:cursor - 1]
    right, depth = cursor + 1, 1
    while right < len(text) and depth:
        if text[right] == "\\":
            right += 2
            continue
        depth += (text[right] == "(") - (text[right] == ")")
        right += 1
    if depth:
        raise ValidationError("У ссылки не закрыта скобка URL.")
    return label, unescape(text[cursor + 1:right - 1]), right, image


class TelegramMarkdownParser:
    def __init__(self, builder):
        self.builder = builder

    def parse(self, text, *, depth=0, blocks=True):
        if depth > 64:
            raise ValidationError("Слишком глубокая вложенность разметки.")
        position = 0
        while position < len(text):
            if text[position] == "\\" and position + 1 < len(text) and ord(text[position + 1]) <= 126:
                self.builder.add(text[position + 1])
                position += 2
                continue
            if blocks and (position == 0 or text[position - 1] == "\n"):
                end = self._quote(text, position, depth)
                if end is not None:
                    position = end
                    continue
            if text.startswith("```", position) or text[position] == "`":
                end = self._code(text, position)
                if end is not None:
                    position = end
                    continue
            match = LEGACY_EMOJI.match(text, position)
            if match:
                self.builder.emoji(match["id"], match["emoji"])
                position = match.end()
                continue
            link = read_link(text, position)
            if link:
                label, url, end, image = link
                kind, attributes = link_entity(url, image=image)
                start = self.builder.offset
                if kind == "custom_emoji":
                    self.builder.emoji(attributes["custom_emoji_id"], unescape(label))
                else:
                    self.parse(label, depth=depth + 1, blocks=False)
                    self.builder.entity(kind, start, **attributes)
                position = end
                continue
            match = EMOJI_ID.match(text, position)
            if match:
                self.builder.emoji(match[1])
                position = match.end()
                continue
            # MarkdownV2 uses an empty bold entity to separate quotes/underline.
            if text.startswith("**", position) and (text.startswith(">", position + 2)
                                                      or text.startswith("__", position + 2)):
                position += 2
                continue
            formatted = False
            for marker, kind in _FORMATS:
                if not text.startswith(marker, position):
                    continue
                end = closing_position(text, marker, position + len(marker))
                if end < 0:
                    continue
                start = self.builder.offset
                self.parse(text[position + len(marker):end], depth=depth + 1, blocks=False)
                self.builder.entity(kind, start)
                position = end + len(marker)
                formatted = True
                break
            if formatted:
                continue
            url = _PLAIN_URL.match(text, position)
            if url:
                self.builder.add(unescape(url[0]))
                position = url.end()
                continue
            # Free text may contain unescaped punctuation or literal brackets.
            self.builder.add(text[position])
            position += 1

    def _code(self, text, position):
        marker = "```" if text.startswith("```", position) else "`"
        end = closing_position(text, marker, position + len(marker))
        if end < 0:
            return None
        contents = text[position + len(marker):end]
        attributes = {}
        if marker == "```":
            language = re.match(r"([a-zA-Z0-9_+.-]*)\n", contents)
            if language:
                if language[1]:
                    attributes["language"] = language[1]
                contents = contents[language.end():]
        start = self.builder.offset
        self.builder.add(re.sub(r"\\([`\\])", r"\1", contents))
        self.builder.entity("pre" if marker == "```" else "code", start, **attributes)
        return end + len(marker)

    def _quote(self, text, position, depth):
        start_position = position
        lines = []
        while position < len(text):
            prefix = "**>" if text.startswith("**>", position) else ">"
            if not text.startswith(prefix, position):
                break
            if lines and prefix == "**>":
                break
            end = text.find("\n", position)
            end = len(text) if end < 0 else end
            lines.append(text[position + len(prefix):end])
            position = end + 1
        if not lines:
            return None
        contents = "\n".join(lines)
        expandable = contents.endswith("||") and not contents.endswith("\\||")
        if expandable:
            contents = contents[:-2]
        start = self.builder.offset
        self.parse(contents, depth=depth + 1, blocks=False)
        self.builder.entity("expandable_blockquote" if expandable else "blockquote", start)
        if position <= len(text):
            self.builder.add("\n")
        return position if position > start_position else None
