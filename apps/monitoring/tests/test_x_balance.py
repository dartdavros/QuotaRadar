"""Credit API validation, cached balance availability, and status-strip rendering."""
from decimal import Decimal
from unittest.mock import Mock, patch

import httpx
from django.core.cache import cache
from django.template.loader import render_to_string
from django.test import SimpleTestCase, override_settings

from apps.monitoring.dashboard.balance import load_x_balance
from apps.monitoring.dashboard.report import Dashboard, OK
from apps.monitoring.x_api import XApiClient, XApiResponseError, XApiTemporaryError


class XCreditApiTests(SimpleTestCase):
    def test_returns_official_total_including_free_credits_and_zero(self):
        http = Mock()
        client = XApiClient(http_client=http, bearer_token="test-token")
        for amount in (6.38, 0):
            with self.subTest(amount=amount):
                http.get.return_value = httpx.Response(200, json={"data": {
                    "total_balance": amount, "prepaid_balance": 1, "free_balance": 2,
                }})
                self.assertEqual(client.get_credit_balance(), Decimal(str(amount)))
        http.get.assert_called_with("https://api.x.com/2/usage/credits", params={},
                                    headers={"Authorization": "Bearer test-token"})

    def test_rejects_missing_partial_or_invalid_balance(self):
        http = Mock()
        client = XApiClient(http_client=http, bearer_token="test-token")
        payloads = [{}, {"data": []}, {"data": {"total_balance": 1}, "errors": [{}]}]
        payloads += [{"data": {"total_balance": value}} for value in (None, True, "6.38", -1)]
        for payload in payloads:
            with self.subTest(payload=payload):
                http.get.return_value = httpx.Response(200, json=payload)
                with self.assertRaises(XApiResponseError):
                    client.get_credit_balance()


@override_settings(CACHES={"default": {
    "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
    "LOCATION": "x-balance-tests",
}})
class CachedXBalanceTests(SimpleTestCase):
    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    @patch("apps.monitoring.dashboard.balance.XApiClient")
    def test_page_reloads_reuse_balance_and_zero_is_a_valid_amount(self, client_class):
        client = client_class.return_value.__enter__.return_value
        for amount, expected in ((Decimal("6.38"), "$6.38"), (Decimal("0"), "$0.00")):
            with self.subTest(amount=amount):
                cache.clear()
                client_class.reset_mock()
                client.get_credit_balance.return_value = amount
                self.assertEqual(load_x_balance(), expected)
                self.assertEqual(load_x_balance(), expected)
                client_class.assert_called_once_with(timeout_seconds=5)

    @patch("apps.monitoring.dashboard.balance.XApiClient")
    def test_failed_refresh_shows_unavailable_instead_of_zero_or_old_balance(self, client_class):
        client = client_class.return_value.__enter__.return_value
        client.get_credit_balance.return_value = Decimal("6.38")
        self.assertEqual(load_x_balance(), "$6.38")
        cache.clear()
        client.get_credit_balance.side_effect = XApiTemporaryError("unavailable")
        self.assertEqual(load_x_balance(), "Недоступен")
        calls = client_class.call_count
        self.assertEqual(load_x_balance(), "Недоступен")
        self.assertEqual(client_class.call_count, calls)

    def test_status_strip_places_balance_before_existing_refresh_button(self):
        for display in ("$6.38", "$0.00", "Недоступен"):
            with self.subTest(display=display):
                dashboard = Dashboard(generated_at="03.10.2026", level=OK,
                    headline="ВСЁ РАБОТАЕТ", checks=[], errors=[], x_balance=display)
                html = render_to_string("admin/monitoring/dashboard.html", {"dashboard": dashboard})
                self.assertIn('class="hp-balance-value">' + display, html)
                self.assertLess(html.index("Баланс X"), html.index("Проверить снова"))
