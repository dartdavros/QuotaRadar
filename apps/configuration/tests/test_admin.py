from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse


class AdminAvailabilityTests(TestCase):
    def test_admin_login_page_is_available(self) -> None:
        response = self.client.get(reverse("admin:login"))

        self.assertEqual(response.status_code, 200)


class SystemConfigurationAdminTests(TestCase):
    def setUp(self) -> None:
        self.user = get_user_model().objects.create_superuser(
            username="configuration-root",
            email="configuration-root@example.test",
            password="test-password",
        )
        self.client.force_login(self.user)

    def test_poll_limits_are_editable(self) -> None:
        response = self.client.get(
            reverse("admin:configuration_systemconfiguration_change", args=(1,))
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="bootstrap_post_limit"')
        self.assertContains(response, 'name="regular_poll_post_limit"')
        self.assertContains(response, 'name="historical_backfill_post_limit"')
        self.assertContains(response, 'name="telegram_message_timezone"')
