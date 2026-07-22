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


class TwoFactorLoginTemplateTests(TestCase):
    """The two-factor login page must render with the Django admin design, not
    the package's Bootstrap CDN template."""

    def test_login_page_does_not_load_bootstrap_or_reminder(self) -> None:
        response = self.client.get(reverse("two_factor:login"))

        self.assertEqual(response.status_code, 200)
        body = response.content.decode("utf-8")
        self.assertNotIn("cdnjs.cloudflare.com", body)
        self.assertNotIn("Provide a template named", body)

    def test_login_page_uses_admin_login_stylesheet(self) -> None:
        response = self.client.get(reverse("two_factor:login"))

        self.assertContains(response, "admin/css/login.css")
        self.assertContains(response, "admin/css/base.css")

    def test_login_page_renders_admin_form_markup(self) -> None:
        response = self.client.get(reverse("two_factor:login"))

        self.assertContains(response, 'id="login-form"')
        self.assertContains(response, "form-row")
        self.assertContains(response, "submit-row")
