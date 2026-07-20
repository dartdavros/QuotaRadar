"""Official X API v2 client built on the mandatory proxy-backed HTTP factory."""

from __future__ import annotations

import time
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import Any

from apps.configuration.http_client import (
    ExternalHttpConfigurationError,
    ExternalHttpRequestError,
    SafeHttpClient,
    create_http_client,
)
from apps.secrets.crypto import SecretDecryptionError
from apps.secrets.models import EncryptedSecret, SecretCode
from apps.secrets.services import SecretNotConfiguredError, get_secret

X_API_BASE_URL = "https://api.x.com"
_X_REQUEST_TIMEOUT_SECONDS = 30
_TWEET_FIELDS = ",".join(
    (
        "id",
        "text",
        "created_at",
        "author_id",
        "entities",
        "referenced_tweets",
        "note_tweet",
        "article",
        "attachments",
        "edit_history_tweet_ids",
        "in_reply_to_user_id",
    )
)
_EXPANSIONS = ",".join(
    (
        "referenced_tweets.id",
        "referenced_tweets.id.author_id",
        "attachments.media_keys",
    )
)
_MEDIA_FIELDS = "media_key,type,url,preview_image_url,alt_text"


class XApiError(RuntimeError):
    """Base class for sanitized X API failures."""


class XApiConfigurationError(XApiError):
    """Required credentials or proxy configuration are unavailable."""


class XApiAuthenticationError(XApiError):
    """The configured X bearer token was rejected."""


class XApiForbiddenError(XApiError):
    """The X application has insufficient access."""


class XApiNotFoundError(XApiError):
    """The requested X resource does not exist."""


class XApiResponseError(XApiError):
    """X returned a permanent or malformed response."""


class XApiTemporaryError(XApiError):
    """X or the proxy failed temporarily."""


class XApiRateLimitError(XApiTemporaryError):
    """X rate limit response with a safe retry deadline."""

    def __init__(self, reset_at: int | None) -> None:
        super().__init__("X API rate limit exceeded.")
        self.reset_at = reset_at

    def retry_after_seconds(self, *, now: float | None = None) -> int:
        current = int(now if now is not None else time.time())
        if self.reset_at is None:
            return 60
        return max(self.reset_at - current + 1, 1)


@dataclass(frozen=True, slots=True)
class XTimelinePage:
    posts: tuple[dict[str, Any], ...]
    includes: dict[str, Any]
    meta: dict[str, Any]
    errors: tuple[dict[str, Any], ...]


class XApiClient:
    """Read-only App-Only Bearer Token client for the required X endpoints."""

    def __init__(
        self,
        *,
        http_client: SafeHttpClient | None = None,
        bearer_token: str | None = None,
    ) -> None:
        self._owns_http_client = http_client is None
        try:
            self._bearer_token = bearer_token or get_secret(SecretCode.X_BEARER_TOKEN)
            self._http_client = http_client or create_http_client(
                timeout_seconds=_X_REQUEST_TIMEOUT_SECONDS
            )
        except (
            ExternalHttpConfigurationError,
            SecretNotConfiguredError,
            SecretDecryptionError,
            EncryptedSecret.DoesNotExist,
        ):
            raise XApiConfigurationError(
                "X API access is disabled because its configuration is unavailable."
            ) from None

    def __enter__(self) -> "XApiClient":
        if self._owns_http_client:
            self._http_client.__enter__()
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> bool | None:  # type: ignore[no-untyped-def]
        if self._owns_http_client:
            return self._http_client.__exit__(exc_type, exc_value, traceback)
        return None

    def close(self) -> None:
        if self._owns_http_client:
            self._http_client.close()

    def lookup_users(self, usernames: Sequence[str]) -> dict[str, str]:
        normalized = [username.strip() for username in usernames if username.strip()]
        if not normalized:
            return {}
        payload = self._get_json(
            "/2/users/by",
            params={
                "usernames": ",".join(normalized),
                "user.fields": "id,username",
            },
        )
        users = payload.get("data") or []
        if not isinstance(users, list) or any(
            not isinstance(user, dict) for user in users
        ):
            raise XApiResponseError("X user lookup returned malformed data.")

        result: dict[str, str] = {}
        for user in users:
            username = user.get("username")
            user_id = user.get("id")
            if not isinstance(username, str) or not isinstance(user_id, str):
                raise XApiResponseError("X user lookup returned malformed data.")
            if not user_id.isdigit():
                raise XApiResponseError("X user lookup returned an invalid User ID.")
            result[username.casefold()] = user_id
        return result

    def iter_user_posts(
        self,
        user_id: str,
        *,
        since_id: str | None,
    ) -> Iterator[XTimelinePage]:
        if not user_id.isdigit():
            raise XApiResponseError("Configured X User ID is invalid.")
        if since_id and not since_id.isdigit():
            raise XApiResponseError("Stored X Post cursor is invalid.")

        pagination_token: str | None = None
        seen_tokens: set[str] = set()
        while True:
            params: dict[str, str | int] = {
                "max_results": 100,
                "exclude": "retweets",
                "tweet.fields": _TWEET_FIELDS,
                "expansions": _EXPANSIONS,
                "media.fields": _MEDIA_FIELDS,
            }
            if since_id:
                params["since_id"] = since_id
            if pagination_token:
                params["pagination_token"] = pagination_token

            payload = self._get_json(f"/2/users/{user_id}/tweets", params=params)
            data = payload.get("data") or []
            includes = payload.get("includes") or {}
            meta = payload.get("meta") or {}
            errors = payload.get("errors") or []
            if (
                not isinstance(data, list)
                or any(not isinstance(item, dict) for item in data)
                or not isinstance(includes, dict)
            ):
                raise XApiResponseError("X timeline returned malformed data.")
            if (
                not isinstance(meta, dict)
                or not isinstance(errors, list)
                or any(not isinstance(item, dict) for item in errors)
            ):
                raise XApiResponseError("X timeline returned malformed metadata.")

            yield XTimelinePage(
                posts=tuple(data),
                includes=includes,
                meta=meta,
                errors=tuple(item for item in errors if isinstance(item, dict)),
            )

            next_token = meta.get("next_token")
            if next_token is None or next_token == "":
                break
            if not isinstance(next_token, str) or next_token in seen_tokens:
                raise XApiResponseError(
                    "X timeline returned an invalid pagination token."
                )
            seen_tokens.add(next_token)
            pagination_token = next_token

    def _get_json(self, path: str, *, params: dict[str, Any]) -> dict[str, Any]:
        try:
            response = self._http_client.get(
                f"{X_API_BASE_URL}{path}",
                params=params,
                headers={"Authorization": f"Bearer {self._bearer_token}"},
            )
        except ExternalHttpRequestError:
            raise XApiTemporaryError("X API request failed.") from None

        self._raise_for_status(response.status_code, response.headers)
        try:
            payload = response.json()
        except (TypeError, ValueError):
            raise XApiResponseError("X API returned invalid JSON.") from None
        if not isinstance(payload, dict):
            raise XApiResponseError("X API returned malformed JSON.")
        return payload

    @staticmethod
    def _raise_for_status(status_code: int, headers: Any) -> None:
        if 200 <= status_code < 300:
            return
        if status_code == 401:
            raise XApiAuthenticationError("X API rejected the configured bearer token.")
        if status_code == 403:
            raise XApiForbiddenError(
                "X API access is forbidden for the configured app."
            )
        if status_code == 404:
            raise XApiNotFoundError("X API resource was not found.")
        if status_code == 429:
            raw_reset = headers.get("x-rate-limit-reset")
            try:
                reset_at = int(raw_reset) if raw_reset is not None else None
            except (TypeError, ValueError):
                reset_at = None
            raise XApiRateLimitError(reset_at)
        if 500 <= status_code < 600:
            raise XApiTemporaryError("X API is temporarily unavailable.")
        raise XApiResponseError(f"X API request failed with HTTP {status_code}.")
