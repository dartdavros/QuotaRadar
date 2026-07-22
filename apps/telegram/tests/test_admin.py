from unittest.mock import patch

from django.contrib.admin.helpers import ACTION_CHECKBOX_NAME
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.telegram.models import (
    Delivery,
    DeliveryStatus,
    DeliveryTarget,
    DeliveryTargetType,
)

from .helpers import create_relevant_analysis
from tests._otp import force_login_verified


class DeliveryAdminTests(TestCase):
    def setUp(self) -> None:
        self.user = get_user_model().objects.create_superuser(
            username="root-deliveries",
            email="root-deliveries@example.test",
            password="test-password",
        )
        force_login_verified(self.client, self.user)
        self.analysis = create_relevant_analysis(external_id="admin-delivery-5001")
        self.target = DeliveryTarget.objects.create(
            target_type=DeliveryTargetType.CHANNEL,
            telegram_chat_id="@quota_delivery_admin",
        )
        self.delivery = Delivery.objects.create(
            analysis=self.analysis,
            target=self.target,
            status=DeliveryStatus.FAILED,
            attempts=3,
            last_attempt_at=timezone.now(),
            last_error="Telegram chat rejected the delivery.",
        )

    def test_changelist_exposes_bulk_requeue_action(self) -> None:
        response = self.client.get(reverse("admin:telegram_delivery_changelist"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "Вернуть выбранные ошибочные доставки в очередь",
        )
        self.assertContains(response, ACTION_CHECKBOX_NAME)

    @patch("apps.telegram.tasks.deliver_analysis.delay")
    def test_bulk_action_requeues_failed_delivery(self, delay) -> None:
        response = self.client.post(
            reverse("admin:telegram_delivery_changelist"),
            {
                "action": "requeue_failed_deliveries",
                ACTION_CHECKBOX_NAME: [str(self.delivery.pk)],
                "index": "0",
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Поставлено в очередь Telegram: 1.")
        delay.assert_called_once_with(self.analysis.pk, self.target.pk)
        self.delivery.refresh_from_db()
        self.assertEqual(self.delivery.status, DeliveryStatus.PENDING)
        self.assertEqual(self.delivery.attempts, 0)
        self.assertIsNone(self.delivery.last_attempt_at)
        self.assertIsNone(self.delivery.next_attempt_at)
        self.assertIsNone(self.delivery.sent_at)
        self.assertEqual(self.delivery.telegram_message_id, "")
        self.assertEqual(self.delivery.last_error, "")
