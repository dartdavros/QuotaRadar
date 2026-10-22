from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from apps.analysis.models import Analysis
from apps.analysis.reset_signals import CODEX_RESET_AUTHOR_ID
from apps.analysis.series_reset import SERIES_RESET_MODEL
from apps.analysis.tasks import analyze_post
from apps.configuration.models import SystemConfiguration
from apps.sources.models import Source, SourcePost, SourcePostProcessingStatus, SourceSubscription
from apps.telegram.models import Delivery, DeliveryStatus, DeliveryTarget


@patch("apps.analysis.tasks.create_llm_client", side_effect=AssertionError("Series must not call LLM"))
@patch("apps.analysis.tasks.render_prompt", side_effect=AssertionError("Series must not render an LLM prompt"))
@patch("apps.telegram.services._dispatch_deliveries")
class SeriesResetTaskTests(TestCase):
    def setUp(self):
        self.source = Source.objects.get(username="thsottiaux")
        self.source.x_user_id = CODEX_RESET_AUTHOR_ID
        self.source.save(update_fields=("x_user_id",))
        SourceSubscription.objects.filter(source=self.source, feed="quota").update(enabled=True)
        self.target = DeliveryTarget.objects.create(
            target_type="channel", telegram_chat_id="-1001234567890", enabled=True, feed="quota",
        )

    def post(self, text="Day 10/ Reset", *, external_id="2110595484180214059", published_at=None):
        return SourcePost.objects.create(
            source=self.source, external_id=external_id, text=text, normalized_text=text,
            published_at=published_at or timezone.now(),
            source_url=f"https://x.com/thsottiaux/status/{external_id}",
            raw_data={"post": {"id": external_id, "author_id": CODEX_RESET_AUTHOR_ID}},
        )

    def test_real_day_formats_persist_and_dispatch_once_without_llm(self, dispatch, render, client):
        for day, text in (
            ("6", "Day 6/ Reset"), ("8", "Day 8/ Reset"),
            ("10", "The reports of my reset button being lost are greatly exaggerated\nDay 10/ Reset"),
        ):
            with self.subTest(day=day):
                post = self.post(text, external_id=f"21000000000000000{day}")
                dispatch.reset_mock()
                with self.captureOnCommitCallbacks(execute=True):
                    first = analyze_post.run(post.pk)
                    second = analyze_post.run(post.pk)
                self.assertEqual(first["status"], "ok")
                self.assertEqual(first["queued_deliveries"], 1)
                self.assertEqual(second["status"], "already_analyzed")
                self.assertEqual(second["queued_deliveries"], 0)
                self.assertEqual(Delivery.objects.filter(analysis__source_post=post).count(), 1)
                dispatch.assert_called_once()
                analysis = Analysis.objects.get(source_post=post)
                self.assertEqual(analysis.model, SERIES_RESET_MODEL)
                self.assertFalse(analysis.is_fallback)
                self.assertEqual(analysis.event_type, "quota_reset")
                self.assertEqual(analysis.message_ru, f"Объявлен сброс лимитов Codex — день {day}.")
                post.refresh_from_db()
                self.assertEqual(post.processing_status, SourcePostProcessingStatus.ANALYZED_RELEVANT)
        client.assert_not_called()
        render.assert_not_called()

    def test_series_does_not_change_llm_availability_state(self, dispatch, render, client):
        post = self.post()
        with patch("apps.analysis.tasks.record_llm_success") as success, \
                patch("apps.analysis.tasks.record_llm_failure") as failure:
            analyze_post.run(post.pk)
        success.assert_not_called()
        failure.assert_not_called()

    def test_missing_llm_configuration_does_not_block_series(self, dispatch, render, client):
        cfg = SystemConfiguration.load()
        SystemConfiguration.objects.filter(pk=cfg.pk).update(llm_model="", llm_base_url="")
        result = analyze_post.run(self.post().pk)
        self.assertTrue(result["is_relevant"])
        self.assertEqual(result["status"], "ok")
        client.assert_not_called()

    def test_stale_series_post_keeps_existing_freshness_gate(self, dispatch, render, client):
        published_at = timezone.now() - timedelta(minutes=40)
        post = self.post(published_at=published_at)
        result = analyze_post.run(post.pk)
        self.assertTrue(result["is_relevant"])
        self.assertEqual(result["queued_deliveries"], 0)
        self.assertFalse(Delivery.objects.exists())
        dispatch.assert_not_called()
        post.refresh_from_db()
        self.assertEqual(post.published_at, published_at)

    def test_manual_sent_post_is_not_rewritten_or_resent(self, dispatch, render, client):
        post = self.post()
        analysis = Analysis.objects.create(
            source_post=post, is_relevant=True, event_type="quota_reset", provider="openai",
            product="codex", title_ru="Ручной заголовок", message_ru="Сообщение владельца.",
            model="manual/owner-approved", prompt_version=4, delivery_fanout_completed_at=timezone.now(),
            raw_response={"manual_override": {"authorized_by": "owner"}},
        )
        Delivery.objects.create(
            analysis=analysis, target=self.target, status=DeliveryStatus.SENT, telegram_message_id="98",
        )
        self.assertEqual(analyze_post.run(post.pk)["status"], "already_analyzed")
        analysis.refresh_from_db()
        self.assertEqual(analysis.model, "manual/owner-approved")
        self.assertEqual(analysis.title_ru, "Ручной заголовок")
        self.assertEqual(Delivery.objects.get().telegram_message_id, "98")
        dispatch.assert_not_called()

    def test_completed_negative_is_not_automatically_backfilled(self, dispatch, render, client):
        post = self.post()
        Analysis.objects.create(
            source_post=post, is_relevant=False, provider="openai", product="codex",
            model="old-model", prompt_version=4,
        )
        result = analyze_post.run(post.pk)
        self.assertEqual(result["status"], "already_analyzed")
        self.assertFalse(result["is_relevant"])
        self.assertFalse(Delivery.objects.exists())
        dispatch.assert_not_called()
