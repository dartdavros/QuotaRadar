"""Factual support and editorial readiness are independent gates."""
from types import SimpleNamespace

from django.test import SimpleTestCase, TestCase

from apps.news.errors import NewsPolicyError
from apps.news.models import NewsConfiguration
from apps.news.schemas import (EditorialVerificationPayload, HistoricalEditorialVerificationPayload,
                               VerificationPayload, WritingPayload)
from apps.news.text_review import validate_review, verification_schema


class EditorialTests(SimpleTestCase):
    def writing(self, text="Теперь изменения проверяются до слияния."):
        return WritingPayload(title="Codex получил проверку изменений", text=text)

    def test_supported_facts_do_not_override_a_style_rejection(self):
        verdict = EditorialVerificationPayload(supported=True, editorial_quality=False, reason="Повторяет заголовок")
        with self.assertRaisesMessage(NewsPolicyError, verdict.reason):
            validate_review(self.writing(), verdict)

    def test_good_style_does_not_override_unsupported_facts(self):
        verdict = EditorialVerificationPayload(supported=False, editorial_quality=True, reason="Выдумана доступность")
        with self.assertRaisesMessage(NewsPolicyError, verdict.reason):
            validate_review(self.writing(), verdict)

    def test_a_short_factual_news_passes_without_a_benefit_paragraph(self):
        validate_review(self.writing(), EditorialVerificationPayload(
            supported=True, editorial_quality=True, reason="Подтверждено"))

    def test_audience_labels_are_blocked_even_with_an_old_custom_verifier(self):
        with self.assertRaises(NewsPolicyError):
            validate_review(self.writing("Вайбкодерам это экономит время."),
                            VerificationPayload(supported=True, reason=""))

    def test_historical_and_custom_prompts_keep_their_contracts(self):
        config = SimpleNamespace(verification_prompt=SimpleNamespace(code="news_verification", version=3))
        self.assertIs(verification_schema(config, True), HistoricalEditorialVerificationPayload)
        config.verification_prompt.code = "custom"
        self.assertIs(verification_schema(config, False), VerificationPayload)


class EditorialDefaultsTests(TestCase):
    def test_default_prompts_and_schema_have_one_consistent_editorial_policy(self):
        config = NewsConfiguration.load()
        prompt = config.writing_prompt
        self.assertEqual((prompt.code, prompt.version, prompt.is_active), ("news_writing", 5, True))
        self.assertIn('"title" — заголовок', prompt.system_prompt)
        self.assertIn('"text" — сама новость', prompt.system_prompt)
        self.assertIn("объём задают факты", prompt.system_prompt.casefold())
        self.assertNotIn("Вайбкодеру это экономит", prompt.system_prompt)
        self.assertNotIn("400–750", WritingPayload.model_fields["text"].description)
        self.assertEqual(config.verification_prompt.version, 3)
        self.assertIn("editorial_quality", config.verification_prompt.system_prompt)
