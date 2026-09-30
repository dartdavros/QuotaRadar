"""Real bundled brand assets and the approved image, without network generation."""
from io import BytesIO
from types import SimpleNamespace

from django.test import SimpleTestCase
from PIL import Image

from apps.news.cover_art import ASSETS, compose, reference_image
from apps.news.cover_brands import official_logo
from apps.news.cover_client import CoverBlocked


class CoverArtTests(SimpleTestCase):
    def test_official_brand_catalog_is_complete_and_compositing_keeps_aspect_ratio(self):
        for product in ("Claude Code", "Claude Sonnet 5.5", "Anthropic", "Cursor", "Codex", "Gemini"):
            with self.subTest(product=product):
                brand, path = official_logo(product, [])
                output = compose(reference_image(), path)
                with Image.open(BytesIO(output)) as image:
                    self.assertEqual(image.size, (1376, 768))
                    self.assertEqual(image.format, "JPEG")
                self.assertLess(len(output), 1_000_000)

    def test_unknown_main_product_does_not_borrow_the_source_company_logo(self):
        posts = [SimpleNamespace(source=SimpleNamespace(provider="openai"))]
        with self.assertRaises(CoverBlocked):
            official_logo("Unknown partner tool", posts)
        self.assertEqual(official_logo("Pro subscription", posts)[0], "openai")

    def test_damaged_or_non_landscape_outputs_are_rejected(self):
        with self.assertRaises(CoverBlocked):
            compose(b"not an image", ASSETS / "claude-code.png")
        portrait = BytesIO()
        Image.new("RGB", (768, 1376)).save(portrait, format="PNG")
        with self.assertRaises(CoverBlocked):
            compose(portrait.getvalue(), ASSETS / "claude-code.png")
