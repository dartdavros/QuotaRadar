"""Durable generated media, one paid claim and the real Telegram request builder."""
from contextlib import ExitStack
from hashlib import sha256
from unittest.mock import patch

from django.test import TestCase

from apps.configuration.models import SystemConfiguration
from apps.news.cover_art import reference_image
from apps.news.cover_client import CoverBlocked, GeneratedImage, MODEL
from apps.news.covers import ensure_cover
from apps.news.models import MediaAsset, NewsPublication
from apps.news.payload import publication_hash
from apps.news.transport import NewsTransport, media_reference
from .cover_cases import make_publication


class CoverPersistenceTests(TestCase):
    def setUp(self):
        self.pub, self.config, self.post, self.facts, self.writing = make_publication()
        settings = SystemConfiguration.load()
        settings.llm_base_url = "https://openrouter.ai/api/v1"
        settings.save()
        self.image = GeneratedImage(reference_image(), MODEL, {"cost": 0.067})

    def ensure(self):
        ensure_cover(self.pub, self.config, self.writing, [self.post])

    def make_cover(self):
        with patch("apps.news.covers.generate", return_value=self.image) as generate:
            self.ensure()
        generate.assert_called_once()
        return self.pub.media.get()

    def test_generated_content_is_reused_from_database_by_a_different_worker(self):
        asset = self.make_cover()
        self.assertEqual(asset.origin, "generated")
        self.assertEqual(sha256(bytes(asset.generated_content)).hexdigest(), asset.checksum)
        self.assertEqual(asset.generation_metadata["model"], MODEL)
        self.pub = NewsPublication.objects.get(pk=self.pub.pk)
        with patch("apps.news.covers.generate") as generate:
            self.ensure()
        generate.assert_not_called()
        self.assertFalse(asset.file)
        self.assertEqual(self.pub.media.count(), 1)

    def test_failed_or_interrupted_generation_is_never_automatically_paid_for_twice(self):
        with patch("apps.news.covers.generate", side_effect=CoverBlocked("network uncertain")) as generate:
            with self.assertRaises(CoverBlocked):
                self.ensure()
            with self.assertRaises(CoverBlocked):
                self.ensure()
        generate.assert_called_once()
        self.pub.refresh_from_db()
        self.assertIsNotNone(self.pub.cover_requested_at)
        self.assertFalse(self.pub.media.exists())

    def test_original_attachment_bypasses_generation_and_unconfigured_provider(self):
        MediaAsset.objects.create(publication=self.pub, post=self.post, media_key="original", kind="photo",
                                  position=0, url="https://pbs.twimg.com/original.jpg")
        with patch("apps.news.covers.generate") as generate, patch("apps.news.covers.validate_provider") as provider:
            self.ensure()
        generate.assert_not_called()
        provider.assert_not_called()

    def test_stale_preparation_does_not_claim_a_new_generation(self):
        NewsPublication.objects.filter(pk=self.pub.pk).update(attempts=self.pub.attempts + 1)
        with patch("apps.news.covers.generate") as generate, self.assertRaises(CoverBlocked):
            self.ensure()
        generate.assert_not_called()
        self.pub.refresh_from_db()
        self.assertIsNone(self.pub.cover_requested_at)

    def test_disabling_publication_during_text_review_prevents_a_paid_request(self):
        type(self.config).objects.filter(pk=self.config.pk).update(publishing_enabled=False)
        with patch("apps.news.covers.generate") as generate, self.assertRaises(CoverBlocked):
            self.ensure()
        generate.assert_not_called()
        self.pub.refresh_from_db()
        self.assertIsNone(self.pub.cover_requested_at)

    def test_a_saved_cover_does_not_silently_illustrate_changed_sources(self):
        self.make_cover()
        self.post.normalized_text = "A different event."
        with patch("apps.news.covers.generate") as generate, self.assertRaises(CoverBlocked):
            self.ensure()
        generate.assert_not_called()

    def test_generated_checksum_is_frozen_and_corrupted_bytes_are_not_sent(self):
        asset = self.make_cover()
        self.pub.rendered = "Проверенная новость"
        self.pub.payload_hash = publication_hash(self.pub)
        frozen = self.pub.payload_hash
        asset.checksum = "0" * 64
        asset.save()
        self.assertNotEqual(publication_hash(self.pub), frozen)
        asset.checksum = sha256(bytes(asset.generated_content)).hexdigest()
        asset.generated_content = b"corrupted"
        asset.save()
        with ExitStack() as stack:
            transport = NewsTransport()
            transport.stack, transport.bot_identity = stack, "bot"
            with self.assertRaisesMessage(ValueError, "повреждено"):
                transport.prepare(self.pub)

    def test_generated_photo_upload_works_without_a_worker_cache_or_public_url(self):
        asset = self.make_cover()
        self.pub.rendered = "Проверенная новость"
        self.pub.payload_hash = publication_hash(self.pub)
        with ExitStack() as stack:
            transport = NewsTransport()
            transport.stack, transport.bot_identity = stack, "bot"
            transport.prepare(self.pub)
            self.assertEqual(transport.method, "sendPhoto")
            self.assertEqual(transport.payload["photo"], "attach://asset0")
            self.assertEqual(transport.files["asset0"][1].read(), bytes(asset.generated_content))
            self.assertFalse(transport.remote_media)
        asset.telegram_file_id, asset.telegram_bot_identity = "telegram-file", "bot"
        self.assertEqual(media_reference(asset, self.pub, "bot", 0), "telegram-file")
        self.assertEqual(media_reference(asset, self.pub, "different-bot", 0), "attach://asset0")
