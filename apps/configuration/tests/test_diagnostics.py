from unittest.mock import Mock, patch

from django.test import TestCase

from apps.configuration.diagnostics import collect_diagnostics
from apps.secrets.models import EncryptedSecret, SecretCode


class ConfigurationDiagnosticsTests(TestCase):
    def test_disabled_or_missing_proxy_is_a_valid_direct_configuration(self) -> None:
        for missing_record in (False, True):
            with self.subTest(missing_record=missing_record):
                if missing_record:
                    EncryptedSecret.objects.filter(code=SecretCode.PROXY_URL).delete()
                results = collect_diagnostics()
                result = next(item for item in results if item.name == "proxy_url")
                self.assertEqual(result.status, "ok")
                self.assertIn("прямое подключение", result.detail)

    @patch("apps.configuration.diagnostics.create_http_client")
    def test_proxy_test_uses_common_client_factory(self, create_client: Mock) -> None:
        client = create_client.return_value.__enter__.return_value
        client.head.return_value.status_code = 204

        results = collect_diagnostics(test_proxy=True)

        create_client.assert_called_once_with()
        client.head.assert_called_once_with("https://example.com/")
        proxy_result = next(item for item in results if item.name == "proxy_connection")
        self.assertEqual(proxy_result.status, "ok")
        self.assertNotIn("credential", proxy_result.detail.lower())
