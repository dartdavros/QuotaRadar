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

    def test_campaign_form_has_editor_and_preview(self):
        response = self.client.get(reverse("admin:advertising_campaign_change", args=[self.campaign.pk]))
        self.assertEqual(response.status_code, 200)
        for value in ("id_body", "advertising/preview.js", "data-preview-url"):
            self.assertContains(response, value)
        self.assertNotContains(response, 'id="id_link_label"')

    def test_over_limit_form_is_rejected_server_side(self):
        response = self.client.post(reverse("admin:advertising_campaign_change", args=[self.campaign.pk]), {
            "target": self.target.pk, "body": "я" * 200,
            "total_posts": 2, "enabled": "on", "_save": "Сохранить"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "превышает 200")
        self.campaign.refresh_from_db()
        self.assertFalse(self.campaign.body)

    def test_preview_uses_real_post_and_safe_formatted_links(self):
        response = self.client.post(reverse("admin:advertising_campaign_preview"), {
            "target": self.target.pk,
            "body": "🤖[5397681122542893003] [**Купить Claude**](https://example.com/?a=1&b=2)",
        })
        self.assertEqual(response.status_code, 200)
        html = response.json()["html"]
        self.assertIn("Опубликовано:", html)
        self.assertIn('href="https://example.com/?a=1&amp;b=2"', html)
        self.assertIn('<strong>Купить Claude</strong></a>', html)
        self.assertNotIn("5397681122542893003]", html)

    def test_placement_journal_displays_frozen_post(self):
        prepare_delivery(self.delivery, "Новость")
        placement = Placement.objects.get(delivery=self.delivery)
        response = self.client.get(reverse("admin:advertising_placement_change", args=[placement.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Рекомендация: ")
        self.assertNotContains(response, 'id="id_telegram_message_id"')
