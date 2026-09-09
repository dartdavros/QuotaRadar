from unittest.mock import Mock, patch

import httpx
from django.test import TestCase

from apps.analysis.llm import (
    LlmAuthenticationError,
    LlmStructuredOutputError,
    LlmTemporaryError,
    OpenAICompatibleLlmClient,
)
from apps.analysis.tests.helpers import load_fixture
from apps.configuration.models import SystemConfiguration


class OpenAICompatibleLlmClientTests(TestCase):
    def setUp(self) -> None:
        self.configuration = SystemConfiguration.load()
        self.configuration.llm_provider = "openai_compatible"
        self.configuration.llm_base_url = "https://llm.example/api/v1"
        self.configuration.llm_model = "test-model"
        self.configuration.llm_temperature = "0.100"
        self.configuration.llm_max_tokens = 500
        self.configuration.save()
        self.http_client = Mock()

    def response(self, status_code: int, payload: object) -> httpx.Response:
        return httpx.Response(status_code, json=payload)

    @patch("apps.analysis.llm.get_secret", return_value="secret-key")
    @patch("apps.analysis.llm.create_http_client")
    def test_default_client_is_created_by_shared_proxy_factory(
        self,
        create_http_client: Mock,
        get_secret: Mock,
    ) -> None:
        client = OpenAICompatibleLlmClient(configuration=self.configuration)

        create_http_client.assert_called_once_with(
            timeout_seconds=self.configuration.llm_timeout_seconds
        )
        get_secret.assert_called_once()
        self.assertIsNotNone(client)

    def test_valid_fixture_is_parsed_and_request_uses_structured_output(self) -> None:
        self.http_client.post.return_value = self.response(
            200, load_fixture("quota_increase.json")
        )
        client = OpenAICompatibleLlmClient(
            configuration=self.configuration,
            http_client=self.http_client,
            api_key="secret-key",
        )

        result = client.analyze(system_prompt="system", user_prompt="user")

        self.assertEqual(result.payload.event_type, "quota_increase")
        call = self.http_client.post.call_args
        self.assertEqual(call.args[0], "https://llm.example/api/v1/chat/completions")
        self.assertEqual(call.kwargs["headers"]["Authorization"], "Bearer secret-key")
        response_format = call.kwargs["json"]["response_format"]
        self.assertEqual(response_format["type"], "json_schema")
        self.assertTrue(response_format["json_schema"]["strict"])

    def test_raw_line_breaks_inside_string_values_are_paragraphs_not_errors(self) -> None:
        # Verbatim shape of a production answer from ai.api.cloud.yandex.net: paragraphs
        # separated by real newlines inside the JSON string, which strict JSON forbids.
        content = ('{"text": "В Cursor теперь доступна модель Muse Spark 1.3 от Meta.' + chr(10) + chr(10) +
                   'Модель может улучшить работу с кодом в редакторе.", '
                   '"title": "В Cursor доступна модель Muse Spark 1.3 от Meta"}')
        self.assertIn(chr(10), content)
        raw = {"choices": [{"message": {"role": "assistant", "content": content}}]}
        self.http_client.post.return_value = self.response(200, raw)
        from apps.news.schemas import WritingPayload
        client = OpenAICompatibleLlmClient(
            configuration=self.configuration,
            http_client=self.http_client,
            api_key="secret-key",
            response_model=WritingPayload,
        )

        result = client.analyze(system_prompt="system", user_prompt="user")

        self.assertEqual(result.payload.title, "В Cursor доступна модель Muse Spark 1.3 от Meta")
        self.assertEqual(result.payload.text.count(chr(10)*2), 1)

    def test_invalid_structured_output_preserves_raw_response_for_failure_record(
        self,
    ) -> None:
        raw = {"choices": [{"message": {"content": '{"is_relevant":"yes"}'}}]}
        self.http_client.post.return_value = self.response(200, raw)
        client = OpenAICompatibleLlmClient(
            configuration=self.configuration,
            http_client=self.http_client,
            api_key="secret-key",
        )

        with self.assertRaises(LlmStructuredOutputError) as raised:
            client.analyze(system_prompt="system", user_prompt="user")

        self.assertEqual(raised.exception.raw_response, raw)

    def test_401_is_permanent_authentication_error(self) -> None:
        self.http_client.post.return_value = self.response(401, {})
        client = OpenAICompatibleLlmClient(
            configuration=self.configuration,
            http_client=self.http_client,
            api_key="secret-key",
        )

        with self.assertRaises(LlmAuthenticationError):
            client.analyze(system_prompt="system", user_prompt="user")

    def test_5xx_is_temporary_error(self) -> None:
        self.http_client.post.return_value = self.response(503, {})
        client = OpenAICompatibleLlmClient(
            configuration=self.configuration,
            http_client=self.http_client,
            api_key="secret-key",
        )

        with self.assertRaises(LlmTemporaryError):
            client.analyze(system_prompt="system", user_prompt="user")
