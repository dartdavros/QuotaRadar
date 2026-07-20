from contextlib import contextmanager
from unittest.mock import Mock, patch

from django.test import TestCase

from apps.analysis.llm import (
    LlmAnalysisResponse,
    LlmStructuredOutputError,
    LlmTemporaryError,
)
from apps.analysis.models import Analysis
from apps.analysis.schemas import AnalysisPayload
from apps.analysis.tasks import analyze_post
from apps.analysis.tests.helpers import make_source_post
from apps.configuration.models import SystemConfiguration
from apps.sources.models import SourcePostProcessingStatus


@contextmanager
def acquired_lock(source_post_id: int):
    yield True


@patch("apps.analysis.tasks.source_post_analysis_lock", acquired_lock)
class AnalyzePostTaskTests(TestCase):
    def setUp(self) -> None:
        self.configuration = SystemConfiguration.load()
        self.configuration.llm_provider = "openai_compatible"
        self.configuration.llm_base_url = "https://llm.example/api/v1"
        self.configuration.llm_model = "test-model"
        self.configuration.retry_count = 2
        self.configuration.save()
        self.post = make_source_post()

    def response(self, *, relevant: bool) -> LlmAnalysisResponse:
        return LlmAnalysisResponse(
            payload=AnalysisPayload.model_validate(
                {
                    "is_relevant": relevant,
                    "event_type": "quota_increase" if relevant else None,
                    "provider": "openai",
                    "product": "codex",
                    "title_ru": "Codex: повышены лимиты" if relevant else None,
                    "message_ru": (
                        "OpenAI увеличила недельные лимиты Codex на 50%."
                        if relevant
                        else None
                    ),
                }
            ),
            raw_response={"id": "completion"},
        )

    @patch("apps.analysis.tasks.queue_analysis_deliveries")
    @patch("apps.analysis.tasks.create_llm_client")
    def test_relevant_post_is_analyzed_once_and_delivery_fanout_is_rechecked(
        self,
        create_client: Mock,
        queue_deliveries: Mock,
    ) -> None:
        client = Mock()
        client.analyze.return_value = self.response(relevant=True)
        create_client.return_value.__enter__.return_value = client
        first_queue = Mock(delivery_ids=(10, 11))
        second_queue = Mock(delivery_ids=())
        queue_deliveries.side_effect = (first_queue, second_queue)

        first = analyze_post.run(self.post.pk)
        second = analyze_post.run(self.post.pk)

        self.assertEqual(first["status"], "ok")
        self.assertEqual(first["queued_deliveries"], 2)
        self.assertEqual(second["status"], "already_analyzed")
        self.assertEqual(second["queued_deliveries"], 0)
        self.assertEqual(Analysis.objects.count(), 1)
        client.analyze.assert_called_once()
        self.assertEqual(queue_deliveries.call_count, 2)

    @patch("apps.analysis.tasks.create_llm_client")
    def test_irrelevant_post_stops_without_delivery_state(
        self, create_client: Mock
    ) -> None:
        client = Mock()
        client.analyze.return_value = self.response(relevant=False)
        create_client.return_value.__enter__.return_value = client

        result = analyze_post.run(self.post.pk)

        self.assertFalse(result["is_relevant"])
        self.post.refresh_from_db()
        self.assertEqual(
            self.post.processing_status,
            SourcePostProcessingStatus.ANALYZED_IRRELEVANT,
        )

    @patch("apps.analysis.tasks.create_llm_client")
    def test_invalid_structured_output_requests_retry(
        self, create_client: Mock
    ) -> None:
        client = Mock()
        client.analyze.side_effect = LlmStructuredOutputError(
            raw_response={"choices": []}
        )
        create_client.return_value.__enter__.return_value = client

        with patch.object(
            analyze_post,
            "retry",
            side_effect=RuntimeError("retry requested"),
        ) as retry:
            with self.assertRaisesRegex(RuntimeError, "retry requested"):
                analyze_post.run(self.post.pk)

        retry.assert_called_once()
        self.assertFalse(Analysis.objects.exists())

    @patch("apps.analysis.tasks.create_llm_client")
    def test_exhausted_retries_persist_failed_analysis(
        self, create_client: Mock
    ) -> None:
        client = Mock()
        client.analyze.side_effect = LlmTemporaryError("LLM request failed.")
        create_client.return_value.__enter__.return_value = client

        analyze_post.push_request(retries=self.configuration.retry_count)
        try:
            result = analyze_post.run(self.post.pk)
        finally:
            analyze_post.pop_request()

        self.assertEqual(result["status"], "failed")
        analysis = Analysis.objects.get(source_post=self.post)
        self.assertIsNone(analysis.is_relevant)
        self.assertEqual(analysis.error, "LLM request failed.")
        self.post.refresh_from_db()
        self.assertEqual(self.post.processing_status, SourcePostProcessingStatus.FAILED)

    @patch("apps.analysis.tasks.create_llm_client")
    def test_temporary_error_requests_configured_retry(
        self, create_client: Mock
    ) -> None:
        client = Mock()
        client.analyze.side_effect = LlmTemporaryError("LLM request failed.")
        create_client.return_value.__enter__.return_value = client

        with patch.object(
            analyze_post,
            "retry",
            side_effect=RuntimeError("retry requested"),
        ) as retry:
            with self.assertRaisesRegex(RuntimeError, "retry requested"):
                analyze_post.run(self.post.pk)

        retry.assert_called_once()
        self.assertEqual(retry.call_args.kwargs["countdown"], 30)
        self.assertEqual(retry.call_args.kwargs["max_retries"], 2)
        self.assertFalse(Analysis.objects.exists())
