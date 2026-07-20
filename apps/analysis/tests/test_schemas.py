import json

from django.test import SimpleTestCase
from pydantic import ValidationError

from apps.analysis.schemas import AnalysisPayload
from apps.analysis.tests.helpers import load_fixture


class AnalysisPayloadTests(SimpleTestCase):
    def test_all_supported_event_fixtures_validate(self) -> None:
        for filename, event_type in (
            ("quota_reset.json", "quota_reset"),
            ("quota_increase.json", "quota_increase"),
            ("quota_extension.json", "quota_extension"),
        ):
            raw = load_fixture(filename)
            content = raw["choices"][0]["message"]["content"]

            payload = AnalysisPayload.model_validate(json.loads(content))

            self.assertTrue(payload.is_relevant)
            self.assertEqual(payload.event_type, event_type)

    def test_irrelevant_fixture_validates_with_null_message_fields(self) -> None:
        raw = load_fixture("irrelevant.json")
        content = raw["choices"][0]["message"]["content"]

        payload = AnalysisPayload.model_validate(json.loads(content))

        self.assertFalse(payload.is_relevant)
        self.assertIsNone(payload.event_type)
        self.assertIsNone(payload.title_ru)
        self.assertIsNone(payload.message_ru)

    def test_json_schema_limits_title_length(self) -> None:
        schema = AnalysisPayload.model_json_schema()
        title_schema = schema["properties"]["title_ru"]

        string_branch = next(
            branch for branch in title_schema["anyOf"] if branch.get("type") == "string"
        )
        self.assertEqual(string_branch["maxLength"], 255)

    def test_extra_fields_are_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            AnalysisPayload.model_validate(
                {
                    "is_relevant": False,
                    "event_type": None,
                    "provider": "openai",
                    "product": "codex",
                    "title_ru": None,
                    "message_ru": None,
                    "source_url": "https://untrusted.example",
                }
            )

    def test_relevant_output_requires_all_message_fields(self) -> None:
        with self.assertRaises(ValidationError):
            AnalysisPayload.model_validate(
                {
                    "is_relevant": True,
                    "event_type": "quota_reset",
                    "provider": "openai",
                    "product": "codex",
                    "title_ru": None,
                    "message_ru": None,
                }
            )
