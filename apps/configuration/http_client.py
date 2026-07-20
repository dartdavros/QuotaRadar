"""Mandatory proxy-backed HTTP clients for every external integration."""

from __future__ import annotations

from types import TracebackType
from typing import Any, Self
from urllib.parse import urlsplit

import httpx

from apps.secrets.crypto import SecretDecryptionError
from apps.secrets.models import EncryptedSecret, SecretCode
from apps.secrets.services import SecretNotConfiguredError, get_secret

_DEFAULT_TIMEOUT_SECONDS = 30.0


class ExternalHttpConfigurationError(RuntimeError):
    """Raised before networking when the mandatory proxy is unavailable."""


class ExternalHttpRequestError(RuntimeError):
    """Sanitized networking error that excludes credentials and response bodies."""


def validate_proxy_url(proxy_url: str) -> None:
    try:
        parsed = urlsplit(proxy_url)
        port = parsed.port
    except ValueError:
        raise ExternalHttpConfigurationError(
            "Configured proxy URL is invalid."
        ) from None

    if (
        parsed.scheme.lower() not in {"http", "https"}
        or not parsed.hostname
        or any(character.isspace() for character in proxy_url)
        or parsed.query
        or parsed.fragment
        or (parsed.path not in {"", "/"})
        or (port is not None and not 1 <= port <= 65535)
    ):
        raise ExternalHttpConfigurationError("Configured proxy URL is invalid.")


def _build_timeout(timeout_seconds: float | int | None) -> httpx.Timeout:
    value = float(timeout_seconds or _DEFAULT_TIMEOUT_SECONDS)
    if value <= 0:
        raise ExternalHttpConfigurationError("External HTTP timeout must be positive.")
    return httpx.Timeout(
        timeout=value,
        connect=min(value, 10.0),
        pool=min(value, 5.0),
    )


def _load_proxy_url() -> str:
    try:
        proxy_url = get_secret(SecretCode.PROXY_URL)
    except SecretNotConfiguredError:
        raise ExternalHttpConfigurationError(
            "External HTTP access is disabled because proxy_url is not configured."
        ) from None
    except (SecretDecryptionError, EncryptedSecret.DoesNotExist):
        raise ExternalHttpConfigurationError(
            "External HTTP access is disabled because proxy_url is unavailable."
        ) from None
    validate_proxy_url(proxy_url)
    return proxy_url


class SafeHttpClient:
    """Small httpx wrapper that sanitizes transport exceptions."""

    def __init__(self, client: httpx.Client) -> None:
        self._client = client

    def __enter__(self) -> Self:
        self._client.__enter__()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None:
        return self._client.__exit__(exc_type, exc_value, traceback)

    def close(self) -> None:
        self._client.close()

    def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        try:
            return self._client.request(method, url, **kwargs)
        except httpx.HTTPError:
            raise ExternalHttpRequestError("External HTTP request failed.") from None

    def get(self, url: str, **kwargs: Any) -> httpx.Response:
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs: Any) -> httpx.Response:
        return self.request("POST", url, **kwargs)

    def head(self, url: str, **kwargs: Any) -> httpx.Response:
        return self.request("HEAD", url, **kwargs)


class SafeAsyncHttpClient:
    """Async counterpart of :class:`SafeHttpClient`."""

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def __aenter__(self) -> Self:
        await self._client.__aenter__()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None:
        return await self._client.__aexit__(exc_type, exc_value, traceback)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        try:
            return await self._client.request(method, url, **kwargs)
        except httpx.HTTPError:
            raise ExternalHttpRequestError("External HTTP request failed.") from None

    async def get(self, url: str, **kwargs: Any) -> httpx.Response:
        return await self.request("GET", url, **kwargs)

    async def post(self, url: str, **kwargs: Any) -> httpx.Response:
        return await self.request("POST", url, **kwargs)


def create_http_client(*, timeout_seconds: float | int | None = None) -> SafeHttpClient:
    proxy_url = _load_proxy_url()
    try:
        client = httpx.Client(
            proxy=proxy_url,
            timeout=_build_timeout(timeout_seconds),
            trust_env=False,
            follow_redirects=True,
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
            headers={"User-Agent": "QuotaRadar/1.0"},
        )
    except (ValueError, httpx.HTTPError):
        raise ExternalHttpConfigurationError(
            "External HTTP client initialization failed."
        ) from None
    return SafeHttpClient(client)


def create_async_http_client(
    *,
    timeout_seconds: float | int | None = None,
) -> SafeAsyncHttpClient:
    proxy_url = _load_proxy_url()
    try:
        client = httpx.AsyncClient(
            proxy=proxy_url,
            timeout=_build_timeout(timeout_seconds),
            trust_env=False,
            follow_redirects=True,
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
            headers={"User-Agent": "QuotaRadar/1.0"},
        )
    except (ValueError, httpx.HTTPError):
        raise ExternalHttpConfigurationError(
            "External HTTP client initialization failed."
        ) from None
    return SafeAsyncHttpClient(client)
