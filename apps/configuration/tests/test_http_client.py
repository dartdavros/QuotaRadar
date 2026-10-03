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
from apps.secrets.crypto import SecretDecryptionError
from apps.secrets.models import EncryptedSecret


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
    def test_creates_client_with_configured_proxy(
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

    def test_both_factories_use_direct_connection_without_configured_proxy(self) -> None:
        for factory, class_name in (
            (create_http_client, "Client"),
            (create_async_http_client, "AsyncClient"),
        ):
            for error in (SecretNotConfiguredError, EncryptedSecret.DoesNotExist):
                with self.subTest(factory=factory.__name__, error=error.__name__):
                    with (
                        patch("apps.configuration.http_client.get_secret", side_effect=error("missing")),
                        patch(f"apps.configuration.http_client.httpx.{class_name}") as client_class,
                    ):
                        factory()
                        self.assertIsNone(client_class.call_args.kwargs["proxy"])
                        self.assertFalse(client_class.call_args.kwargs["trust_env"])

    def test_both_factories_reject_broken_active_proxy_without_direct_fallback(self) -> None:
        for factory, class_name in (
            (create_http_client, "Client"),
            (create_async_http_client, "AsyncClient"),
        ):
            for secret_options in (
                {"return_value": "socks5://user:password@proxy.example:1080"},
                {"side_effect": SecretDecryptionError("unavailable")},
            ):
                with self.subTest(factory=factory.__name__, options=secret_options):
                    with (
                        patch("apps.configuration.http_client.get_secret", **secret_options),
                        patch(f"apps.configuration.http_client.httpx.{class_name}") as client_class,
                    ):
                        with self.assertRaises(ExternalHttpConfigurationError):
                            factory()
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
