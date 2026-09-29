from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.advertising.models import Placement
from apps.advertising.services import prepare_delivery
from tests._otp import force_login_verified
from .base import AdvertisingTestCase


class AdvertisingAdminTests(AdvertisingTestCase):
    def setUp(self):
        super().setUp()
        user = get_user_model().objects.create_superuser("ads-test-owner", "owner@example.test", "test-password")
        force_login_verified(self.client, user)

    def test_campaign_form_has_counter_and_separate_link_fields(self):
        response = self.client.get(reverse("admin:advertising_campaign_change", args=[self.campaign.pk]))
        self.assertEqual(response.status_code, 200)
        for value in ("id_message", "id_link_label", "id_url", "advertising/counter.js", "id_message_helptext"):
            self.assertContains(response, value)

    def test_over_limit_form_is_rejected_server_side(self):
        response = self.client.post(reverse("admin:advertising_campaign_change", args=[self.campaign.pk]), {
            "target": self.target.pk, "message": "я" * 200, "link_label": "Программа", "url": "https://example.com",
            "total_posts": 2, "enabled": "on", "_save": "Сохранить"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "превышает 200")
        self.campaign.refresh_from_db()
        self.assertNotEqual(self.campaign.message, "я" * 200)

    def test_placement_journal_displays_frozen_post(self):
        prepare_delivery(self.delivery, "Новость")
        placement = Placement.objects.get(delivery=self.delivery)
        response = self.client.get(reverse("admin:advertising_placement_change", args=[placement.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Рекомендация: ")
        self.assertNotContains(response, 'id="id_telegram_message_id"')
