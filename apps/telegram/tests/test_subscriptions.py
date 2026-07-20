from django.test import TestCase

from apps.telegram.models import DeliveryTarget, DeliveryTargetType
from apps.telegram.subscriptions import (
    disable_private_chat,
    enable_private_chat,
    get_private_chat_status,
)


class SubscriptionTests(TestCase):
    def test_start_is_idempotent(self) -> None:
        first = enable_private_chat("12345")
        second = enable_private_chat("12345")

        self.assertTrue(first.changed)
        self.assertFalse(second.changed)
        self.assertEqual(DeliveryTarget.objects.count(), 1)
        self.assertTrue(DeliveryTarget.objects.get().enabled)

    def test_stop_is_idempotent_and_does_not_create_missing_target(self) -> None:
        first = disable_private_chat("12345")
        second = disable_private_chat("12345")

        self.assertFalse(first.enabled)
        self.assertFalse(second.changed)
        self.assertFalse(DeliveryTarget.objects.exists())

    def test_stop_disables_existing_subscription(self) -> None:
        target = DeliveryTarget.objects.create(
            target_type=DeliveryTargetType.PRIVATE_CHAT,
            telegram_chat_id="12345",
        )

        result = disable_private_chat("12345")

        target.refresh_from_db()
        self.assertTrue(result.changed)
        self.assertFalse(target.enabled)
        self.assertFalse(get_private_chat_status("12345").enabled)
