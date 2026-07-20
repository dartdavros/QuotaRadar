from django.test import TestCase

from apps.analysis.models import Analysis
from apps.analysis.quality import (
    TELEGRAM_MESSAGE_MAX_LENGTH,
    AnalysisQualityError,
    build_notification_text,
    validate_payload_for_post,
)
from apps.analysis.schemas import AnalysisPayload
from apps.analysis.tests.helpers import make_source_post


class AnalysisQualityTests(TestCase):
    def setUp(self) -> None:
        self.post = make_source_post()

    def payload(self, **overrides: object) -> AnalysisPayload:
        values: dict[str, object] = {
            "is_relevant": True,
            "event_type": "quota_increase",
            "provider": "openai",
            "product": "codex",
            "title_ru": "Codex: повышены лимиты",
            "message_ru": "OpenAI увеличила недельные лимиты Codex на 50%.",
        }
        values.update(overrides)
        return AnalysisPayload.model_validate(values)

    def test_source_provider_and_product_must_match(self) -> None:
        payload = self.payload(provider="anthropic", product="claude_code")

        with self.assertRaisesRegex(AnalysisQualityError, "does not match"):
            validate_payload_for_post(payload=payload, source_post=self.post)

    def test_relevant_copy_must_be_russian(self) -> None:
        payload = self.payload(title_ru="Codex limits increased")

        with self.assertRaisesRegex(AnalysisQualityError, "Russian"):
            validate_payload_for_post(payload=payload, source_post=self.post)

    def test_model_generated_links_are_rejected(self) -> None:
        payload = self.payload(message_ru="Подробности: https://example.com")

        with self.assertRaisesRegex(AnalysisQualityError, "must not contain links"):
            validate_payload_for_post(payload=payload, source_post=self.post)

    def test_model_generated_domain_without_scheme_is_rejected(self) -> None:
        payload = self.payload(message_ru="Подробности опубликованы на x.com/example")

        with self.assertRaisesRegex(AnalysisQualityError, "must not contain links"):
            validate_payload_for_post(payload=payload, source_post=self.post)

    def test_final_telegram_length_is_checked_with_source_url(self) -> None:
        payload = self.payload(message_ru="Т" * TELEGRAM_MESSAGE_MAX_LENGTH)

        with self.assertRaisesRegex(AnalysisQualityError, "too long"):
            validate_payload_for_post(payload=payload, source_post=self.post)

    def test_source_url_is_added_only_by_application(self) -> None:
        analysis = Analysis.objects.create(
            source_post=self.post,
            is_relevant=True,
            event_type="quota_increase",
            provider="openai",
            product="codex",
            title_ru="Codex: повышены лимиты",
            message_ru="OpenAI увеличила недельные лимиты Codex на 50%.",
            model="test-model",
            prompt_version=1,
            raw_response={},
        )

        rendered = build_notification_text(analysis)

        self.assertEqual(rendered.count(self.post.source_url), 1)
        self.assertTrue(rendered.endswith(f"Источник: {self.post.source_url}"))
