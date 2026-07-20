from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.test import TestCase

from apps.telegram.models import (
    Delivery,
    DeliveryTarget,
    DeliveryTargetType,
)

from .helpers import create_relevant_analysis


class DeliveryTargetModelTests(TestCase):
    def test_private_chat_requires_positive_numeric_id(self) -> None:
        target = DeliveryTarget(
            target_type=DeliveryTargetType.PRIVATE_CHAT,
            telegram_chat_id="@subscriber",
        )
        with self.assertRaises(ValidationError):
            target.full_clean()

    def test_channel_accepts_username_or_numeric_id(self) -> None:
        username_target = DeliveryTarget(
            target_type=DeliveryTargetType.CHANNEL,
            telegram_chat_id="@quota_radar",
        )
        numeric_target = DeliveryTarget(
            target_type=DeliveryTargetType.CHANNEL,
            telegram_chat_id="-1001234567890",
        )

        username_target.full_clean()
        numeric_target.full_clean()

    def test_chat_id_is_unique_across_target_types(self) -> None:
        DeliveryTarget.objects.create(
            target_type=DeliveryTargetType.PRIVATE_CHAT,
            telegram_chat_id="12345",
        )
        with self.assertRaises(ValidationError):
            DeliveryTarget.objects.create(
                target_type=DeliveryTargetType.CHANNEL,
                telegram_chat_id="12345",
            )


class DeliveryModelTests(TestCase):
    def test_analysis_target_pair_is_unique(self) -> None:
        analysis = create_relevant_analysis()
        target = DeliveryTarget.objects.create(
            target_type=DeliveryTargetType.CHANNEL,
            telegram_chat_id="@quota_radar",
        )
        Delivery.objects.create(analysis=analysis, target=target)

        with self.assertRaises(IntegrityError):
            Delivery.objects.create(analysis=analysis, target=target)
