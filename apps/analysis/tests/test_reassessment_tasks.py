from contextlib import contextmanager
from unittest.mock import Mock, patch

from django.test import TestCase
from django.utils import timezone

from apps.analysis.llm import LlmAnalysisResponse, LlmTemporaryError
from apps.analysis.models import Analysis
from apps.analysis.schemas import AnalysisPayload
from apps.analysis.tasks import analyze_post
from apps.analysis.reset_signals import CODEX_RESET_AUTHOR_ID
from apps.analysis.tests.test_reset_signals import DAY_17
from apps.configuration.models import SystemConfiguration
from apps.monitoring.models import MonitoringEvent
from apps.sources.models import Source, SourcePost, SourcePostProcessingStatus, SourceSubscription


@contextmanager
def acquired_lock(post_id):
    yield True


@patch("apps.analysis.tasks.source_post_analysis_lock", acquired_lock)
@patch("apps.analysis.tasks.queue_analysis_deliveries")
@patch("apps.analysis.tasks.create_llm_client")
class ReassessmentTaskTests(TestCase):
    def setUp(self):
        cfg = SystemConfiguration.load()
        cfg.llm_model = "test-model"
        cfg.save(update_fields=("llm_model",))
        source = Source.objects.get(username="thsottiaux")
        source.x_user_id = CODEX_RESET_AUTHOR_ID
        source.save(update_fields=("x_user_id",))
        SourceSubscription.objects.filter(source=source, feed="quota").update(enabled=True)
        self.post = SourcePost.objects.create(
            source=source, external_id="2109045392684032299",
            text="Global reset by EOD. May the tokens do good things for you.",
            normalized_text="Global reset by EOD. May the tokens do good things for you.",
            source_url="https://x.com/thsottiaux/status/2109045392684032299",
            published_at=timezone.now(), raw_data={"post": {
                "id": "2109045392684032299", "author_id": CODEX_RESET_AUTHOR_ID,
            }},
        )

    def response(self, relevant, response_id, **overrides):
        values = {
            "is_relevant": relevant, "event_type": "quota_reset" if relevant else None,
            "provider": "openai", "product": "codex",
            "title_ru": "[CODEX] Глобальный сброс лимитов" if relevant else None,
            "message_ru": "Объявлен сброс лимитов до конца дня." if relevant else None,
        }
        values.update(overrides)
        return LlmAnalysisResponse(
            payload=AnalysisPayload.model_validate(values), raw_response={"id": response_id},
        )

    def configure(self, create_client, queue, responses):
        client = Mock()
        client.analyze.side_effect = responses
        create_client.return_value.__enter__.return_value = client
        queue.return_value = Mock(delivery_ids=(1,))
        return client

    def test_negative_then_confirmed_reset_is_saved_and_queued_once(self, create_client, queue):
        client = self.configure(create_client, queue, [
            self.response(False, "initial"), self.response(True, "review"),
        ])
        result = analyze_post.run(self.post.pk)
        repeat = analyze_post.run(self.post.pk)
        self.assertEqual(result["status"], "ok")
        self.assertTrue(result["is_relevant"])
        self.assertEqual(repeat["status"], "already_analyzed")
        self.assertEqual(client.analyze.call_count, 2)
        self.assertIn("Повторная оценка", client.analyze.call_args.kwargs["system_prompt"])
        self.assertEqual(
            client.analyze.call_args_list[0].kwargs["user_prompt"],
            client.analyze.call_args_list[1].kwargs["user_prompt"],
        )
        a = Analysis.objects.get(source_post=self.post)
        self.assertEqual(a.event_type, "quota_reset")
        self.assertEqual(a.raw_response["irrelevance_review"]["initial_response"]["id"], "initial")
        self.assertEqual(a.raw_response["irrelevance_review"]["reassessment_response"]["id"], "review")

    def test_repeated_refusal_is_failed_with_both_responses_and_no_delivery(self, create_client, queue):
        client = self.configure(create_client, queue, [
            self.response(False, "initial"), self.response(False, "review"),
        ])
        result = analyze_post.run(self.post.pk)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(client.analyze.call_count, 2)
        queue.assert_not_called()
        self.post.refresh_from_db()
        self.assertEqual(self.post.processing_status, SourcePostProcessingStatus.FAILED)
        a = Analysis.objects.get(source_post=self.post)
        self.assertIsNone(a.is_relevant)
        self.assertIn("не подтвердила quota_reset", a.error)
        self.assertEqual(a.raw_response["initial_response"]["id"], "initial")
        self.assertEqual(a.raw_response["reassessment_response"]["id"], "review")
        self.assertTrue(MonitoringEvent.objects.filter(error_type="SuspiciousIrrelevanceError").exists())

    def test_repeated_refusal_alerts_the_owner_when_the_chat_is_configured(self, create_client, queue):
        cfg = SystemConfiguration.load()
        cfg.reset_alert_chat_id = "-1001234567890"
        cfg.save(update_fields=("reset_alert_chat_id",))
        self.configure(create_client, queue, [
            self.response(False, "initial"), self.response(False, "review"),
        ])
        with patch("apps.analysis.reset_alert.TelegramBotApiClient") as client_class:
            bot = client_class.return_value.__enter__.return_value
            self.assertEqual(analyze_post.run(self.post.pk)["status"], "failed")
        queue.assert_not_called()
        self.assertIn(self.post.text, bot.send_message.call_args.kwargs["text"])

    def test_repeated_refusal_sends_nothing_without_a_configured_chat(self, create_client, queue):
        self.configure(create_client, queue, [
            self.response(False, "initial"), self.response(False, "review"),
        ])
        with patch("apps.analysis.reset_alert.TelegramBotApiClient") as client_class:
            self.assertEqual(analyze_post.run(self.post.pk)["status"], "failed")
        client_class.assert_not_called()

    def test_review_unavailable_fails_without_keyword_fallback(self, create_client, queue):
        client = self.configure(create_client, queue, [
            self.response(False, "initial"), LlmTemporaryError("LLM request failed."),
        ])
        with patch("apps.analysis.tasks.deliver_without_llm") as fallback:
            result = analyze_post.run(self.post.pk)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(client.analyze.call_count, 2)
        queue.assert_not_called()
        fallback.assert_not_called()
        a = Analysis.objects.get(source_post=self.post)
        self.assertIn("повторная оценка недоступна", a.error)
        self.assertFalse(a.is_fallback)

    def test_invalid_review_identity_fails_without_delivery(self, create_client, queue):
        self.configure(create_client, queue, [
            self.response(False, "initial"),
            self.response(True, "review", provider="anthropic", product="claude_code"),
        ])
        self.assertEqual(analyze_post.run(self.post.pk)["status"], "failed")
        queue.assert_not_called()

    def test_initial_positive_does_not_need_second_request(self, create_client, queue):
        client = self.configure(create_client, queue, [self.response(True, "initial")])
        self.assertTrue(analyze_post.run(self.post.pk)["is_relevant"])
        client.analyze.assert_called_once()

    def test_ordinary_negative_does_not_need_second_request(self, create_client, queue):
        self.post.text = self.post.normalized_text = "Codex documentation was updated."
        self.post.save(update_fields=("text", "normalized_text"))
        client = self.configure(create_client, queue, [self.response(False, "initial")])
        self.assertFalse(analyze_post.run(self.post.pk)["is_relevant"])
        client.analyze.assert_called_once()
        queue.assert_not_called()

    def test_global_reset_without_quota_keywords_is_reviewed(self, create_client, queue):
        self.post.text = self.post.normalized_text = "Global reset landing by EOD PST time. Enjoy"
        self.post.save(update_fields=("text", "normalized_text"))
        client = self.configure(create_client, queue, [
            self.response(False, "initial"), self.response(True, "review"),
        ])
        result = analyze_post.run(self.post.pk)
        self.assertTrue(result["is_relevant"])
        self.assertEqual(client.analyze.call_count, 2)

    def test_rebutted_negation_day_post_is_reviewed(self, create_client, queue):
        self.post.text = self.post.normalized_text = DAY_17[1]
        self.post.save(update_fields=("text", "normalized_text"))
        client = self.configure(create_client, queue, [
            self.response(False, "initial"), self.response(True, "review"),
        ])
        result = analyze_post.run(self.post.pk)
        self.assertTrue(result["is_relevant"])
        self.assertEqual(client.analyze.call_count, 2)
        queue.assert_called_once()
