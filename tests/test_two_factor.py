"""Functional tests for the two-factor admin login flow.

These cover the guarantees the OTP integration must keep:

* the admin rejects anyone who is not OTP-verified (logged-out or merely
  password-authenticated);
* the two-factor wizard is reachable so an administrator can bootstrap the
  first device after ``createsuperuser``.
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from tests._otp import force_login_verified


class TwoFactorLoginFlowTests(TestCase):
    def setUp(self) -> None:
        self.user = get_user_model().objects.create_superuser(
            username="two-factor-root",
            email="two-factor-root@example.test",
            password="test-password",
        )

    def test_anonymous_admin_request_redirects_to_two_factor_login(self) -> None:
        response = self.client.get(reverse("admin:index"))

        self.assertEqual(response.status_code, 302)
        self.assertIn("/admin/login/", response["location"])

    def test_admin_login_redirects_to_two_factor_wizard(self) -> None:
        response = self.client.get(reverse("admin:login"))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["location"], "/account/login/?next=/admin/")

    def test_two_factor_login_page_is_reachable(self) -> None:
        response = self.client.get(reverse("two_factor:login"))

        self.assertEqual(response.status_code, 200)

    def test_password_only_session_cannot_reach_admin(self) -> None:
        self.client.force_login(self.user)

        response = self.client.get(reverse("admin:index"))

        self.assertEqual(response.status_code, 302)
        self.assertIn("/admin/login/", response["location"])

    def test_verified_session_reaches_admin(self) -> None:
        force_login_verified(self.client, self.user)

        response = self.client.get(reverse("admin:index"))

        self.assertEqual(response.status_code, 200)

    def test_setup_view_is_reachable_after_password_login(self) -> None:
        """Bootstrap path: an authenticated (but unverified) admin can enroll a device."""
        self.client.force_login(self.user)

        response = self.client.get(reverse("two_factor:setup"))

        self.assertEqual(response.status_code, 200)
