"""Telegram Bot API client using the mandatory proxy-backed HTTP factory."""

from __future__ import annotations

from dataclasses import dataclass
from types import TracebackType
from typing import Any, Self

from apps.configuration.http_client import (
    ExternalHttpConfigurationError,
    ExternalHttpRequestError,
    SafeHttpClient,
    create_http_client,
)
from apps.secrets.crypto import SecretDecryptionError
from apps.secrets.models import EncryptedSecret, SecretCode
from apps.secrets.services import SecretNotConfiguredError, get_secret

TELEGRAM_API_BASE_URL = "https://api.telegram.org"
_DEFAULT_REQUEST_TIMEOUT_SECONDS = 30


class TelegramApiError(RuntimeError):
    """Base class for sanitized Telegram Bot API failures."""


class TelegramConfigurationError(TelegramApiError):
    """The token or mandatory proxy configuration is unavailable."""


class TelegramAuthenticationError(TelegramApiError):
    """Telegram rejected the configured bot token."""


class TelegramTemporaryError(TelegramApiError):
    """A network, rate-limit, or server failure that may succeed later."""

    def __init__(self, message: str, *, retry_after: int | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class TelegramPermanentChatError(TelegramApiError):
    """The requested chat permanently rejected or cannot receive the message."""


class TelegramResponseError(TelegramApiError):
    """Telegram returned a permanent malformed or unsupported response."""


@dataclass(frozen=True, slots=True)
class TelegramUpdate:
    update_id: int
    chat_id: str
    chat_type: str
    text: str


class TelegramBotApiClient:
    """Minimal synchronous client for long polling and message delivery."""

    def __init__(
        self,
        *,
        http_client: SafeHttpClient | None = None,
        token: str | None = None,
        timeout_seconds: int = _DEFAULT_REQUEST_TIMEOUT_SECONDS,
    ) -> None:
        self._owns_http_client = http_client is None
        try:
            self._token = token or get_secret(SecretCode.TELEGRAM_BOT_TOKEN)
            self._http_client = http_client or create_http_client(
                timeout_seconds=timeout_seconds
            )
        except (
            ExternalHttpConfigurationError,
            SecretNotConfiguredError,
            SecretDecryptionError,
            EncryptedSecret.DoesNotExist,
        ):
            raise TelegramConfigurationError(
                "Telegram access is disabled because its configuration is unavailable."
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

    def close(self) -> None:
        if self._owns_http_client:
            self._http_client.close()

    def get_updates(
        self,
        *,
        offset: int | None,
        timeout_seconds: int,
    ) -> tuple[TelegramUpdate, ...]:
        payload: dict[str, Any] = {
            "timeout": timeout_seconds,
            "allowed_updates": ["message"],
        }
        if offset is not None:
            payload["offset"] = offset
        result = self._call("getUpdates", payload=payload)
        if not isinstance(result, list):
            raise TelegramResponseError("Telegram getUpdates returned malformed data.")
        return tuple(
            update for item in result if (update := _parse_update(item)) is not None
        )

    def send_message(self, *, chat_id: str, text: str) -> str:
        result = self._call(
            "sendMessage",
            payload={
                "chat_id": chat_id,
                "text": text,
                "disable_web_page_preview": True,
            },
        )
        if not isinstance(result, dict):
            raise TelegramResponseError("Telegram sendMessage returned malformed data.")
        message_id = result.get("message_id")
        if not isinstance(message_id, int):
            raise TelegramResponseError("Telegram sendMessage omitted message_id.")
        return str(message_id)

    def _call(self, method: str, *, payload: dict[str, Any]) -> object:
        try:
            response = self._http_client.post(
                f"{TELEGRAM_API_BASE_URL}/bot{self._token}/{method}",
                json=payload,
            )
        except ExternalHttpRequestError:
            raise TelegramTemporaryError("Telegram API request failed.") from None

        try:
            body = response.json()
        except (TypeError, ValueError):
            body = None
        if not isinstance(body, dict):
            if response.status_code == 401:
                raise TelegramAuthenticationError(
                    "Telegram rejected the configured bot token."
                )
            if response.status_code == 429 or 500 <= response.status_code < 600:
                raise TelegramTemporaryError("Telegram API is temporarily unavailable.")
            raise TelegramResponseError("Telegram API returned invalid JSON.")

        if 200 <= response.status_code < 300 and body.get("ok") is True:
            return body.get("result")
        _raise_api_error(status_code=response.status_code, body=body)
        raise AssertionError("Unreachable Telegram API error branch.")


def _parse_update(value: object) -> TelegramUpdate | None:
    if not isinstance(value, dict):
        raise TelegramResponseError("Telegram getUpdates returned malformed data.")
    update_id = value.get("update_id")
    if not isinstance(update_id, int):
        raise TelegramResponseError("Telegram update omitted update_id.")

    message = value.get("message")
    if not isinstance(message, dict):
        return None
    text = message.get("text")
    chat = message.get("chat")
    if not isinstance(text, str) or not isinstance(chat, dict):
        return None
    chat_id = chat.get("id")
    chat_type = chat.get("type")
    if not isinstance(chat_id, int) or not isinstance(chat_type, str):
        raise TelegramResponseError("Telegram message contained malformed chat data.")
    return TelegramUpdate(
        update_id=update_id,
        chat_id=str(chat_id),
        chat_type=chat_type,
        text=text,
    )


def _raise_api_error(*, status_code: int, body: dict[str, Any]) -> None:
    error_code = body.get("error_code")
    if not isinstance(error_code, int):
        error_code = status_code
    parameters = body.get("parameters")
    retry_after: int | None = None
    if isinstance(parameters, dict) and isinstance(parameters.get("retry_after"), int):
        retry_after = max(parameters["retry_after"], 1)

    if error_code == 401:
        raise TelegramAuthenticationError("Telegram rejected the configured bot token.")
    if error_code == 429 or error_code >= 500:
        raise TelegramTemporaryError(
            "Telegram API is temporarily unavailable.",
            retry_after=retry_after,
        )
    if error_code in {400, 403, 404}:
        raise TelegramPermanentChatError(
            "Telegram chat is unavailable or rejected the bot."
        )
    raise TelegramResponseError(f"Telegram API request failed with HTTP {error_code}.")
