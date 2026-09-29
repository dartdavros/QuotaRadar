"""Formatting, escaping, safety and entity offsets across both Telegram styles."""
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase

from apps.advertising.markup import render_markup, utf16_length
from apps.advertising.formatting import validate_body


class FreeformMarkupTests(SimpleTestCase):
    def entity_text(self, rendered, entity):
        encoded = rendered.text.encode("utf-16-le")
        return encoded[entity["offset"] * 2:(entity["offset"] + entity["length"]) * 2].decode("utf-16-le")

    def test_exact_requested_copy_with_id_only_shortcut(self):
        body = (
            "[5397681122542893003][**Купить Claude со скидкой 5%**](https://t.me/premkaiobot?start=ad_ya_claude_5_2909)\n"
            "[5208665212483310136][**Купить ChatGPT со скидкой 5%**](https://t.me/premkaiobot?start=ad_ya_chatgpt_5_2909)")
        fallbacks = {"5397681122542893003": "⭐", "5208665212483310136": "✅"}
        # These supplied alternatives check syntax/offsets, not the real sticker artwork.
        rendered = render_markup(body, emoji_fallbacks=fallbacks)
        self.assertEqual(rendered.text, "⭐Купить Claude со скидкой 5%\n✅Купить ChatGPT со скидкой 5%")
        self.assertEqual([item["type"] for item in rendered.entities],
                         ["custom_emoji", "text_link", "bold", "custom_emoji", "text_link", "bold"])
        self.assertEqual(rendered.emoji_fallbacks, fallbacks)
        self.assertEqual(self.entity_text(rendered, rendered.entities[3]), "✅")

    def test_native_markdown_v2_styles_links_code_and_quotes(self):
        rendered = render_markup(
            "*Жирный _курсив_* __подчёркнутый__ ~удалённый~ ||спойлер||\n"
            "[Профиль](tg://user?id=42) `a_b [123]`\n"
            "```python\nprint('пример')\n```\n"
            ">Цитата *жирная*\n>Продолжение\n**>Скрытая цитата||")
        types = {item["type"] for item in rendered.entities}
        self.assertEqual(types, {"bold", "italic", "underline", "strikethrough", "spoiler",
                                 "text_link", "code", "pre", "blockquote", "expandable_blockquote"})
        code = next(item for item in rendered.entities if item["type"] == "code")
        self.assertEqual(self.entity_text(rendered, code), "a_b [123]")
        self.assertIn("print('пример')", rendered.text)

    def test_html_supports_all_text_styles_and_native_emoji(self):
        rendered = render_markup(
            '<b>Жирный <i>курсив</i></b> <u>подчёркнутый</u> <s>удалённый</s> '
            '<tg-spoiler>спойлер</tg-spoiler> <span class="tg-spoiler">ещё</span>\n'
            '<a href="https://example.com?a=1&amp;b=2">Ссылка</a> '
            '<tg-emoji emoji-id="5397681122542893003">👍</tg-emoji>\n'
            '<pre><code class="language-python">a_b [123]</code></pre> '
            '<blockquote expandable>Цитата</blockquote> <code>пример</code>')
        self.assertEqual({item["type"] for item in rendered.entities},
                         {"bold", "italic", "underline", "strikethrough", "spoiler", "text_link",
                          "custom_emoji", "pre", "expandable_blockquote", "code"})
        self.assertEqual(next(item["language"] for item in rendered.entities if item["type"] == "pre"), "python")
        self.assertIn('href="https://example.com?a=1&amp;b=2"', rendered.html)
        self.assertIn("a_b [123]", rendered.text)

    def test_native_emoji_and_date_time_in_both_styles(self):
        bodies = ('![👍](tg://emoji?id=5397681122542893003) ![Завтра](tg://time?unix=1647531900&format=wDT)',
                  '<tg-emoji emoji-id="5397681122542893003">👍</tg-emoji> '
                  '<tg-time unix="1647531900" format="wDT">Завтра</tg-time>')
        first, second = [render_markup(body) for body in bodies]
        self.assertEqual(first.text, second.text)
        self.assertEqual(first.entities, second.entities)

    def test_nested_markdown_v2_example_and_underline_separator(self):
        rendered = render_markup(
            "*bold _italic bold ~italic bold strikethrough ||italic bold strikethrough spoiler||~ "
            "__underline italic bold___ bold*")
        self.assertNotIn("_", rendered.text)
        self.assertEqual({item["type"] for item in rendered.entities},
                         {"bold", "italic", "strikethrough", "spoiler", "underline"})
        self.assertEqual(render_markup("___italic underline_**__").text, "italic underline")

    def test_free_text_escaped_punctuation_and_literal_brackets(self):
        body = "Новости: [текст], цена 5%. + - = {пример}!\nhttps://example.com/a_b\n\\[123\\]"
        rendered = render_markup(body)
        self.assertEqual(rendered.text, body.replace("\\", ""))
        self.assertFalse(rendered.entities)
        self.assertEqual(render_markup("`<b>код</b>`").text, "<b>код</b>")
        self.assertEqual(render_markup("\\<b>текст\\</b>").text, "<b>текст</b>")

    def test_formatted_link_with_nested_styles_and_parentheses(self):
        rendered = render_markup('[**Купить _сейчас_**](https://example.com/a_(b))')
        self.assertEqual(rendered.text, "Купить сейчас")
        self.assertEqual(rendered.entities[0]["url"], "https://example.com/a_(b)")
        self.assertIn("<em>сейчас</em>", rendered.html)

    def test_ids_can_be_anywhere_including_html_and_complex_emoji(self):
        fallbacks = {"5397681122542893003": "👩‍💻"}
        rendered = render_markup("<b>Начало [5397681122542893003] конец</b>", emoji_fallbacks=fallbacks)
        emoji = next(item for item in rendered.entities if item["type"] == "custom_emoji")
        self.assertEqual(emoji["offset"], utf16_length("Начало "))
        self.assertEqual(self.entity_text(rendered, emoji), "👩‍💻")

    def test_preview_never_embeds_user_html_or_unsafe_urls(self):
        rendered = render_markup('<b>&lt;script&gt;alert(1)&lt;/script&gt;</b>')
        self.assertNotIn("<script>", rendered.html)
        for body in ('[Ссылка](javascript:alert(1))', '<b><script>alert(1)</script></b>',
                     '<b><i>Текст</b></i>', '<b><code>нельзя</code></b>'):
            with self.subTest(body=body), self.assertRaises(ValidationError):
                render_markup(body)

    def test_only_actual_platform_length_limits_free_text(self):
        validate_body("я" * 1000)
        validate_body("[Ссылка](https://example.com/" + "x" * 2500 + ")")
        with self.assertRaises(ValidationError):
            validate_body("я" * 4096)

    @patch("apps.advertising.markup_result.resolve_emoji", return_value="👍")
    def test_id_only_requires_readonly_lookup_and_preserves_result(self, lookup):
        rendered = render_markup("Текст [5397681122542893003] текст")
        lookup.assert_called_once_with("5397681122542893003")
        self.assertEqual(rendered.emoji_fallbacks, {"5397681122542893003": "👍"})
        with patch("apps.advertising.markup_result.resolve_emoji") as second_lookup:
            self.assertEqual(render_markup("[5397681122542893003]", emoji_fallbacks=rendered.emoji_fallbacks).text, "👍")
            second_lookup.assert_not_called()
