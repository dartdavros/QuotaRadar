from django.test import TestCase

from apps.analysis.llm import LlmAnalysisResponse
from apps.analysis.schemas import AnalysisPayload
from apps.analysis.services import save_failed_analysis, save_successful_analysis
from apps.analysis.tests.helpers import make_source_post
from apps.configuration.models import SystemConfiguration
from apps.sources.models import SourcePostProcessingStatus


class AnalysisPersistenceTests(TestCase):
    def setUp(self) -> None:
        self.configuration = SystemConfiguration.load()
        self.configuration.llm_model = "test-model"
        self.configuration.save()
        self.post = make_source_post()

    def response(self, *, relevant: bool = True) -> LlmAnalysisResponse:
        payload = AnalysisPayload.model_validate(
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
        )
        return LlmAnalysisResponse(payload=payload, raw_response={"id": "raw"})

    def test_success_is_one_to_one_and_updates_post_status(self) -> None:
        first = save_successful_analysis(
            source_post_id=self.post.pk,
            response=self.response(),
            configuration=self.configuration,
        )
        second = save_successful_analysis(
            source_post_id=self.post.pk,
            response=self.response(),
            configuration=self.configuration,
        )

        self.assertTrue(first.created)
        self.assertFalse(second.created)
        self.assertEqual(first.analysis.pk, second.analysis.pk)
        self.assertEqual(first.analysis.model, "test-model")
        self.assertEqual(first.analysis.prompt_version, 2)
        self.post.refresh_from_db()
        self.assertEqual(
            self.post.processing_status,
            SourcePostProcessingStatus.ANALYZED_RELEVANT,
        )

    def test_irrelevant_result_reaches_terminal_non_delivery_status(self) -> None:
        persisted = save_successful_analysis(
            source_post_id=self.post.pk,
            response=self.response(relevant=False),
            configuration=self.configuration,
        )

        self.assertFalse(persisted.analysis.is_relevant)
        self.post.refresh_from_db()
        self.assertEqual(
            self.post.processing_status,
            SourcePostProcessingStatus.ANALYZED_IRRELEVANT,
        )

    def test_final_failure_is_distinct_from_irrelevant_result(self) -> None:
        analysis = save_failed_analysis(
            source_post_id=self.post.pk,
            configuration=self.configuration,
            error="LLM returned invalid structured output.",
            raw_response={"invalid": True},
        )

        self.assertIsNone(analysis.is_relevant)
        self.assertEqual(analysis.raw_response, {"invalid": True})
        self.post.refresh_from_db()
        self.assertEqual(self.post.processing_status, SourcePostProcessingStatus.FAILED)
