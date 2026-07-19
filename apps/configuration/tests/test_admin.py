from django.test import TestCase
from django.urls import reverse


class AdminAvailabilityTests(TestCase):
    def test_admin_login_page_is_available(self) -> None:
        response = self.client.get(reverse("admin:login"))

        self.assertEqual(response.status_code, 200)
