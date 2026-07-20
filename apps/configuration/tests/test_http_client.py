from unittest.mock import Mock, patch

import httpx
from django.test import SimpleTestCase

from apps.configuration.http_client import (
    ExternalHttpConfigurationError,
    ExternalHttpRequestError,
    create_async_http_client,
    create_http_client,
    validate_proxy_url,
)
from apps.secrets.services import SecretNotConfiguredError


class ProxyUrlValidationTests(SimpleTestCase):
    def test_accepts_authenticated_http_proxy(self) -> None:
        validate_proxy_url("http://user:password@proxy.example:8080")

    def test_rejects_unsupported_scheme_without_echoing_value(self) -> None:
        proxy_url = "socks5://user:top-secret@proxy.example:1080"

        with self.assertRaises(ExternalHttpConfigurationError) as context:
            validate_proxy_url(proxy_url)

        self.assertNotIn(proxy_url, str(context.exception))
        self.assertNotIn("top-secret", str(context.exception))


class HttpClientFactoryTests(SimpleTestCase):
    @patch("apps.configuration.http_client.httpx.Client")
    @patch("apps.configuration.http_client.get_secret")
    def test_creates_client_with_mandatory_proxy(
        self,
        get_secret: Mock,
        client_class: Mock,
    ) -> None:
        get_secret.return_value = "https://user:password@proxy.example:8443"

        client = create_http_client(timeout_seconds=20)

        self.assertIsNotNone(client)
        kwargs = client_class.call_args.kwargs
        self.assertEqual(kwargs["proxy"], get_secret.return_value)
        self.assertFalse(kwargs["trust_env"])
        self.assertTrue(kwargs["follow_redirects"])

    @patch("apps.configuration.http_client.httpx.Client")
    @patch("apps.configuration.http_client.get_secret")
    def test_does_not_attempt_direct_connection_without_proxy(
        self,
        get_secret: Mock,
        client_class: Mock,
    ) -> None:
        get_secret.side_effect = SecretNotConfiguredError("missing")

        with self.assertRaises(ExternalHttpConfigurationError):
            create_http_client()

        client_class.assert_not_called()

    @patch("apps.configuration.http_client.httpx.Client")
    @patch("apps.configuration.http_client.get_secret")
    def test_sanitizes_transport_exception(
        self,
        get_secret: Mock,
        client_class: Mock,
    ) -> None:
        proxy_url = "http://user:password@proxy.example:8080"
        get_secret.return_value = proxy_url
        raw_client = client_class.return_value
        raw_client.request.side_effect = httpx.ProxyError(
            f"Cannot connect to {proxy_url}"
        )

        client = create_http_client()
        with self.assertRaises(ExternalHttpRequestError) as context:
            client.get("https://api.example.test/resource")

        self.assertNotIn(proxy_url, str(context.exception))
        self.assertNotIn("password", str(context.exception))
        self.assertIsNone(context.exception.__cause__)

    @patch("apps.configuration.http_client.httpx.Client")
    @patch("apps.configuration.http_client.get_secret")
    def test_sanitizes_client_initialization_error(
        self,
        get_secret: Mock,
        client_class: Mock,
    ) -> None:
        proxy_url = "http://user:password@proxy.example:8080"
        get_secret.return_value = proxy_url
        client_class.side_effect = ValueError(f"invalid proxy {proxy_url}")

        with self.assertRaises(ExternalHttpConfigurationError) as context:
            create_http_client()

        self.assertNotIn(proxy_url, str(context.exception))
        self.assertIsNone(context.exception.__cause__)

    @patch("apps.configuration.http_client.httpx.AsyncClient")
    @patch("apps.configuration.http_client.get_secret")
    def test_async_factory_uses_same_proxy_policy(
        self,
        get_secret: Mock,
        client_class: Mock,
    ) -> None:
        get_secret.return_value = "http://proxy.example:8080"

        client = create_async_http_client()

        self.assertIsNotNone(client)
        self.assertEqual(
            client_class.call_args.kwargs["proxy"], get_secret.return_value
        )
        self.assertFalse(client_class.call_args.kwargs["trust_env"])
