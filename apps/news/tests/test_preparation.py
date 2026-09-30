"""Only the changed preparation paths: text review, original media and generated covers."""
from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.utils import timezone

from apps.configuration.models import SystemConfiguration
from apps.news.cover_art import reference_image
from apps.news.cover_client import CoverBlocked, GeneratedImage, MODEL
from apps.news.models import InitialFill
from apps.news.preparation import prepare
from apps.news.schemas import EditorialVerificationPayload, HistoricalEditorialVerificationPayload
from .cover_cases import make_publication


class PreparationTests(TestCase):
    def setUp(self):
        self.pub, self.config, self.post, self.facts, self.writing = make_publication()
        settings = SystemConfiguration.load()
        settings.llm_base_url = "https://openrouter.ai/api/v1"
        settings.save()
        self.verdict = EditorialVerificationPayload(supported=True, editorial_quality=True, reason="Подтверждено")
        self.image = GeneratedImage(reference_image(), MODEL, {"cost": 0.067})

    def prepare(self, verdict=None):
        with patch("apps.news.preparation.ask", side_effect=[
                (self.writing, "text-model", {}), (verdict or self.verdict, "text-model", {})]) as ask:
            prepare(self.pub.pk, self.config)
        self.pub.refresh_from_db()
        return ask

    def test_no_original_media_produces_a_frozen_photo_after_both_text_gates(self):
        with patch("apps.news.covers.generate", return_value=self.image) as generate:
            self.prepare()
        generate.assert_called_once()
        self.assertEqual(self.pub.status, "ready")
        self.assertEqual(self.pub.media.get().origin, "generated")
        self.assertEqual(self.pub.prompt_versions, {"writing": 5, "verification": 3})

    def test_existing_photo_remains_original_and_does_not_generate_a_cover(self):
        self.post.raw_data = {"post": {"attachments": {"media_keys": ["original"]}},
            "includes": {"media": [{"media_key": "original", "type": "photo", "url": "https://pbs.twimg.com/a.jpg"}]}}
        self.post.save()
        with patch("apps.news.covers.generate") as generate:
            self.prepare()
        generate.assert_not_called()
        self.assertEqual(self.pub.status, "ready")
        self.assertEqual(self.pub.media.get().origin, "source")

    def test_editorial_rejection_leaves_feedback_and_never_spends_on_a_cover(self):
        verdict = EditorialVerificationPayload(supported=True, editorial_quality=False, reason="Вода вместо фактов")
        with patch("apps.news.covers.generate") as generate:
            self.prepare(verdict)
        generate.assert_not_called()
        self.assertEqual(self.pub.status, "preparing")
        self.assertIn(verdict.reason, self.pub.last_error)
        self.pub.next_attempt_at = None
        self.pub.save()
        with patch("apps.news.covers.generate", return_value=self.image):
            ask = self.prepare()
        self.assertIn(verdict.reason, ask.call_args_list[0].kwargs["data"]["revision_note"])

    def test_unknown_image_result_blocks_publication_without_a_text_only_fallback(self):
        with patch("apps.news.covers.generate", side_effect=CoverBlocked("Результат неизвестен")) as generate:
            self.prepare()
            prepare(self.pub.pk, self.config)
        generate.assert_called_once()
        self.assertEqual(self.pub.status, "blocked")
        self.assertFalse(self.pub.media.exists())

    @override_settings(QUOTARADAR_NEWS_INITIAL_FILL_ALLOWED=True)
    def test_history_keeps_a_supported_text_even_if_its_offer_expired(self):
        now = timezone.now()
        run = InitialFill.objects.create(target=self.pub.target, status="preparing",
            window_start=now-timedelta(days=4), window_end=now, expires_at=now+timedelta(hours=24))
        self.config.collection_enabled = self.config.analysis_enabled = True
        self.config.save()
        self.pub.initial_fill, self.pub.attempts = run, 4
        self.pub.save()
        verdict = HistoricalEditorialVerificationPayload(supported=True, editorial_quality=True,
            reason="Подтверждено", still_relevant=False)
        with patch("apps.news.preparation.ensure_cover"):
            ask = self.prepare(verdict)
        self.assertEqual((self.pub.status, self.pub.attempts), ("ready", 5))
        self.assertIs(ask.call_args.kwargs["schema"], HistoricalEditorialVerificationPayload)
