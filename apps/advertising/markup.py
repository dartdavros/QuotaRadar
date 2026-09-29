"""Free-form Telegram text: MarkdownV2, HTML and the editor's [emoji ID] shortcut."""
import re

from django.core.exceptions import ValidationError

from .markup_html import TelegramHTMLParser
from .markup_markdown import TelegramMarkdownParser
from .markup_result import MarkupBuilder, RenderedMarkup, utf16_length


_HTML_TAG = re.compile(
    r"</?(?:b|strong|i|em|u|ins|s|strike|del|span|tg-spoiler|a|tg-emoji|tg-time|code|pre|blockquote)(?:\s|>)",
    re.IGNORECASE,
)


def render_markup(markup, *, emoji_fallbacks=None):
    markup = markup.replace("\r\n", "\n").replace("\r", "\n")
    builder = MarkupBuilder(emoji_fallbacks)
    # A literal HTML example inside a Markdown code block must remain literal.
    outside_code = re.sub(r"```[\s\S]*?```|`[^`]*`|\\[\x01-\x7e]", "", markup)
    parser = TelegramHTMLParser(builder) if _HTML_TAG.search(outside_code) else TelegramMarkdownParser(builder)
    parser.parse(markup)
    result = builder.finish()
    if not result.text.strip():
        raise ValidationError("Введите текст рекомендации.")
    return result
