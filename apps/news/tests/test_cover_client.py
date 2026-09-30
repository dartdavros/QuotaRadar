"""OpenRouter's real response contract, sanitized failures and absence of paid retries."""
import base64
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from apps.news.cover_art import reference_image
from apps.news.cover_client import CoverBlocked, MODEL, generate, parse_image, validate_provider


class CoverClientTests(SimpleTestCase):
    def test_response_decodes_bytes_and_preserves_actual_usage(self):
        content = reference_image()
        image = parse_image({"data": [{"b64_json": base64.b64encode(content).decode(), "media_type": "image/jpeg"}],
                             "usage": {"cost": 0.067}})
        self.assertEqual(image.content, content)
        self.assertEqual(image.usage["cost"], 0.067)
        self.assertEqual(image.model, MODEL)

    def test_malformed_empty_or_multiple_images_are_not_accepted(self):
        for body in ({}, {"data": []}, {"data": [{"b64_json": "!broken!"}]},
                     {"data": [{"b64_json": ""}]}, {"data": [{}, {}]}):
            with self.subTest(body=body), self.assertRaises(CoverBlocked):
                parse_image(body)

    def test_generation_sends_style_reference_and_does_not_retry_a_failed_request(self):
        client = MagicMock()
        client.__enter__.return_value = client
        client.post.return_value.status_code = 502
        with patch("apps.news.cover_client.validate_provider"), \
                patch("apps.news.cover_client.get_secret", return_value="unit-test-key"), \
                patch("apps.news.cover_client.create_http_client", return_value=client):
            with self.assertRaises(CoverBlocked):
                generate("test prompt", reference_image())
        client.post.assert_called_once()
        args, kwargs = client.post.call_args
        self.assertEqual(args[0], "https://openrouter.ai/api/v1/images")
        self.assertEqual(kwargs["json"]["model"], MODEL)
        self.assertEqual(kwargs["json"]["n"], 1)
        self.assertTrue(kwargs["json"]["input_references"][0]["image_url"]["url"].startswith("data:image/jpeg;base64,"))
        self.assertFalse(kwargs["follow_redirects"])

    def test_other_providers_are_not_silently_substituted(self):
        for url in ("https://llm.example/api/v1", "http://openrouter.ai/api/v1", "https://openrouter.ai/api/v1?key=x"):
            with self.subTest(url=url), patch("apps.news.cover_client.SystemConfiguration.load",
                    return_value=SimpleNamespace(llm_base_url=url)), self.assertRaises(CoverBlocked):
                validate_provider()
