from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.analysis.models import Analysis
from apps.analysis.tests.helpers import make_source_post


class AnalysisModelTests(TestCase):
    def test_failed_analysis_requires_error_and_has_no_relevance_value(self) -> None:
        analysis = Analysis(
            source_post=make_source_post(),
            is_relevant=None,
            provider="openai",
            product="codex",
            model="test-model",
            prompt_version=1,
        )

        with self.assertRaises(ValidationError):
            analysis.full_clean()

    def test_irrelevant_analysis_rejects_message_content(self) -> None:
        analysis = Analysis(
            source_post=make_source_post(),
            is_relevant=False,
            provider="openai",
            product="codex",
            title_ru="Нельзя",
            model="test-model",
            prompt_version=1,
        )

        with self.assertRaises(ValidationError):
            analysis.full_clean()
