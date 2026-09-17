"""The keyword warning that replaces an analysis while the LLM is unavailable."""

from __future__ import annotations

from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from apps.analysis.fallback import (
    agent_name,
    deliver_without_llm,
    fallback_title,
    mentions_reset,
)
from apps.analysis.models import Analysis, AnalysisEventType, AnalysisProduct
from apps.configuration.models import SystemConfiguration
from apps.sources.models import Feed, SourceProvider
from apps.telegram.models import Delivery, DeliveryTarget, DeliveryTargetType
from apps.telegram.services import format_delivery_message

from .helpers import make_source_post


class ResetDetectionTests(TestCase):
    def test_english_reset_forms_are_detected(self) -> None:
        for text in (
            "We just reset rate limits for all Codex users.",
            "Codex usage limits have been reset.",
            "We're resetting limits for everyone today.",
            "This week's limit resets early.",
            "RESET of weekly limits is live.",
        ):
            with self.subTest(text=text):
                self.assertTrue(mentions_reset(text))

    def test_unrelated_posts_are_not_detected(self) -> None:
        for text in (
            "Codex limits are 50% higher this week.",
            "We shipped a new preset for agents.",
            "Hard-resetting is spelled with a hyphen elsewhere.".replace(
                "Hard-resetting", "Rebasing"
            ),
            "",
        ):
            with self.subTest(text=text):
                self.assertFalse(mentions_reset(text))

    def test_agent_names_follow_the_provider(self) -> None:
        self.assertEqual(agent_name(SourceProvider.OPENAI), "Codex")
        self.assertEqual(agent_name(SourceProvider.ANTHROPIC), "Claude Code")
        self.assertIsNone(agent_name(SourceProvider.CURSOR))

    def test_title_names_the_agent(self) -> None:
        self.assertEqual(
            fallback_title("Claude Code"),
            "Claude Code: возможный сброс лимитов",
        )


class DeliverWithoutLlmTests(TestCase):
    def setUp(self) -> None:
        self.configuration = SystemConfiguration.load()
        self.target = DeliveryTarget.objects.create(
            target_type=DeliveryTargetType.CHANNEL,
            telegram_chat_id="@quotaradar_test",
            feed=Feed.QUOTA,
        )

    def _make_fresh_post(self, external_id: str, text: str, **kwargs):
        return make_source_post(
            external_id=external_id,
            normalized_text=text,
            published_at=timezone.now(),
            **kwargs,
        )

    def _deliver(self, post, *, unavailable: bool = True):
        with (
            patch(
                "apps.analysis.fallback.llm_unavailable",
                return_value=unavailable,
            ),
            patch("apps.telegram.services._dispatch_deliveries", return_value=None),
        ):
            return deliver_without_llm(
                source_post=post,
                configuration=self.configuration,
                task_id="task-1",
            )

    def test_reset_post_is_stored_as_a_fallback_analysis(self) -> None:
        post = self._make_fresh_post("9101", "We reset Codex limits for everyone.")

        result = self._deliver(post)

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result["status"], "fallback")
        self.assertEqual(result["queued_deliveries"], 1)
        analysis = Analysis.objects.get(source_post=post)
        self.assertTrue(analysis.is_fallback)
        self.assertTrue(analysis.is_relevant)
        self.assertEqual(analysis.event_type, AnalysisEventType.QUOTA_RESET)
        self.assertEqual(analysis.title_ru, "Codex: возможный сброс лимитов")
        self.assertEqual(analysis.message_ru, "")
        self.assertEqual(analysis.error, "")

    def test_message_is_the_agent_line_and_the_link(self) -> None:
        post = self._make_fresh_post(
            "9102",
            "Usage limits were reset.",
            provider=SourceProvider.ANTHROPIC,
        )
        self._deliver(post)

        analysis = Analysis.objects.get(source_post=post)
        self.assertEqual(
            format_delivery_message(analysis),
            f"Claude Code: возможный сброс лимитов\n{post.source_url}",
        )

    def test_available_llm_produces_no_fallback(self) -> None:
        post = self._make_fresh_post("9103", "We reset Codex limits for everyone.")

        self.assertIsNone(self._deliver(post, unavailable=False))
        self.assertFalse(Analysis.objects.filter(source_post=post).exists())

    def test_post_without_the_keyword_produces_no_fallback(self) -> None:
        post = self._make_fresh_post("9104", "Codex limits are 50% higher this week.")

        self.assertIsNone(self._deliver(post))
        self.assertFalse(Analysis.objects.filter(source_post=post).exists())

    def test_existing_real_analysis_is_never_replaced(self) -> None:
        post = self._make_fresh_post("9105", "We reset Codex limits for everyone.")
        Analysis.objects.create(
            source_post=post,
            is_relevant=False,
            provider=SourceProvider.OPENAI,
            product=AnalysisProduct.CODEX,
            model="test-model",
            prompt_version=1,
        )

        self.assertIsNone(self._deliver(post))
        analysis = Analysis.objects.get(source_post=post)
        self.assertFalse(analysis.is_fallback)
        self.assertFalse(analysis.is_relevant)

    def test_stale_post_is_never_delivered(self) -> None:
        post = make_source_post(
            external_id="9106",
            normalized_text="We reset Codex limits for everyone.",
        )

        result = self._deliver(post)

        assert result is not None
        self.assertEqual(result["queued_deliveries"], 0)
        self.assertFalse(Delivery.objects.filter(analysis__source_post=post).exists())

    def test_running_twice_delivers_once(self) -> None:
        post = self._make_fresh_post("9107", "We reset Codex limits for everyone.")

        self._deliver(post)
        second = self._deliver(post)

        assert second is not None
        self.assertEqual(second["queued_deliveries"], 0)
        self.assertEqual(Analysis.objects.filter(source_post=post).count(), 1)
        self.assertEqual(
            Delivery.objects.filter(analysis__source_post=post).count(), 1
        )
