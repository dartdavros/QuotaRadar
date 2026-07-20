"""Provider-agnostic OpenAI-compatible LLM adapter."""

from __future__ import annotations

import json
from dataclasses import dataclass
from types import TracebackType
from typing import Any, Self

from pydantic import ValidationError as PydanticValidationError

from apps.configuration.http_client import (
    ExternalHttpConfigurationError,
    ExternalHttpRequestError,
    SafeHttpClient,
    create_http_client,
)
from apps.configuration.models import SystemConfiguration
from apps.secrets.crypto import SecretDecryptionError
from apps.secrets.models import EncryptedSecret, SecretCode
from apps.secrets.services import SecretNotConfiguredError, get_secret

from .schemas import AnalysisPayload, structured_output_json_schema


class LlmError(RuntimeError):
    """Base class for sanitized LLM adapter failures."""


class LlmConfigurationError(LlmError):
    """The configured adapter, endpoint, model, key or proxy is unavailable."""


class LlmAuthenticationError(LlmError):
    """The configured API key was rejected."""


class LlmForbiddenError(LlmError):
    """The configured account cannot use the requested endpoint or model."""


class LlmResponseError(LlmError):
    """The provider returned a permanent malformed response."""


class LlmTemporaryError(LlmError):
    """The provider or proxy failed temporarily."""


class LlmStructuredOutputError(LlmTemporaryError):
    """The provider response did not satisfy the server-side schema."""

    def __init__(self, *, raw_response: object | None) -> None:
        super().__init__("LLM returned invalid structured output.")
        self.raw_response = raw_response


@dataclass(frozen=True, slots=True)
class LlmAnalysisResponse:
    payload: AnalysisPayload
    raw_response: dict[str, Any]


class OpenAICompatibleLlmClient:
    """Chat Completions adapter configured entirely from PostgreSQL."""

    ADAPTER_CODE = "openai_compatible"

    def __init__(
        self,
        *,
        configuration: SystemConfiguration,
        http_client: SafeHttpClient | None = None,
        api_key: str | None = None,
    ) -> None:
        _validate_configuration(configuration)
        self._configuration = configuration
        self._owns_http_client = http_client is None
        try:
            self._api_key = api_key or get_secret(SecretCode.LLM_API_KEY)
            self._http_client = http_client or create_http_client(
                timeout_seconds=configuration.llm_timeout_seconds
            )
        except (
            ExternalHttpConfigurationError,
            SecretNotConfiguredError,
            SecretDecryptionError,
            EncryptedSecret.DoesNotExist,
        ):
            raise LlmConfigurationError(
                "LLM access is disabled because its configuration is unavailable."
            ) from None

    def __enter__(self) -> Self:
        if self._owns_http_client:
            self._http_client.__enter__()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None:
        if self._owns_http_client:
            return self._http_client.__exit__(exc_type, exc_value, traceback)
        return None

    def analyze(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
    ) -> LlmAnalysisResponse:
        try:
            response = self._http_client.post(
                _chat_completions_url(self._configuration.llm_base_url),
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json=self._request_payload(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                ),
            )
        except ExternalHttpRequestError:
            raise LlmTemporaryError("LLM request failed.") from None

        _raise_for_status(response.status_code)
        try:
            raw_response = response.json()
        except (TypeError, ValueError):
            raise LlmStructuredOutputError(raw_response=None) from None
        if not isinstance(raw_response, dict):
            raise LlmStructuredOutputError(raw_response=raw_response)

        structured = _extract_structured_content(raw_response)
        try:
            payload = AnalysisPayload.model_validate(structured)
        except PydanticValidationError:
            raise LlmStructuredOutputError(raw_response=raw_response) from None
        return LlmAnalysisResponse(payload=payload, raw_response=raw_response)

    def _request_payload(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
    ) -> dict[str, Any]:
        return {
            "model": self._configuration.llm_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": float(self._configuration.llm_temperature),
            "max_tokens": self._configuration.llm_max_tokens,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "quota_event_analysis",
                    "strict": True,
                    "schema": structured_output_json_schema(),
                },
            },
        }


def create_llm_client(
    *,
    configuration: SystemConfiguration,
) -> OpenAICompatibleLlmClient:
    """Create the configured adapter without provider-specific branching elsewhere."""

    if configuration.llm_provider != OpenAICompatibleLlmClient.ADAPTER_CODE:
        raise LlmConfigurationError("Configured LLM adapter is not supported.")
    return OpenAICompatibleLlmClient(configuration=configuration)


def _validate_configuration(configuration: SystemConfiguration) -> None:
    if not configuration.llm_base_url or not configuration.llm_model:
        raise LlmConfigurationError("LLM endpoint and model must be configured.")


def _chat_completions_url(base_url: str) -> str:
    return f"{base_url.rstrip('/')}/chat/completions"


def _raise_for_status(status_code: int) -> None:
    if 200 <= status_code < 300:
        return
    if status_code == 401:
        raise LlmAuthenticationError("LLM provider rejected the configured API key.")
    if status_code == 403:
        raise LlmForbiddenError("LLM provider denied access to the requested model.")
    if status_code == 429 or 500 <= status_code < 600:
        raise LlmTemporaryError("LLM provider is temporarily unavailable.")
    raise LlmResponseError(f"LLM request failed with HTTP {status_code}.")


def _extract_structured_content(raw_response: dict[str, Any]) -> object:
    try:
        message = raw_response["choices"][0]["message"]
    except (KeyError, IndexError, TypeError):
        raise LlmStructuredOutputError(raw_response=raw_response) from None
    if not isinstance(message, dict):
        raise LlmStructuredOutputError(raw_response=raw_response)

    parsed = message.get("parsed")
    if isinstance(parsed, dict):
        return parsed

    content = message.get("content")
    if not isinstance(content, str):
        raise LlmStructuredOutputError(raw_response=raw_response)
    try:
        return json.loads(content)
    except (TypeError, ValueError):
        raise LlmStructuredOutputError(raw_response=raw_response) from None
