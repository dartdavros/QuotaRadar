from importlib import import_module
from types import SimpleNamespace

from django.apps import apps
from django.db import connection
from django.test import TestCase
from django.utils import timezone

from apps.telegram.models import Delivery, DeliveryTarget, DeliveryTargetType
from .helpers import create_relevant_analysis


class RetirementMigrationTests(TestCase):
    def test_disables_private_targets_and_pending_only_preserving_history_and_channels(self):
        private = DeliveryTarget.objects.create(
            target_type=DeliveryTargetType.PRIVATE_CHAT, telegram_chat_id="12345",
        )
        channel = DeliveryTarget.objects.create(
            target_type=DeliveryTargetType.CHANNEL, telegram_chat_id="@quota_radar",
        )
        analysis = create_relevant_analysis(published_at=timezone.now())
        pending = Delivery.objects.create(analysis=analysis, target=private, next_attempt_at=timezone.now())
        channel_pending = Delivery.objects.create(analysis=analysis, target=channel)
        sent = Delivery.objects.create(
            analysis=create_relevant_analysis(external_id="retired-sent"),
            target=private, status="sent", telegram_message_id="777",
        )
        uncertain = Delivery.objects.create(
            analysis=create_relevant_analysis(external_id="retired-uncertain"),
            target=private, status="uncertain",
        )

        migration = import_module("apps.telegram.migrations.0005_privatechatretirementnotice")
        migration.disable_private_delivery(apps, SimpleNamespace(connection=connection))
        migration.disable_private_delivery(apps, SimpleNamespace(connection=connection))

        for record in (private, channel, pending, channel_pending, sent, uncertain):
            record.refresh_from_db()
        self.assertFalse(private.enabled)
        self.assertTrue(channel.enabled)
        self.assertEqual(pending.status, "failed")
        self.assertIsNone(pending.next_attempt_at)
        self.assertEqual(channel_pending.status, "pending")
        self.assertEqual(sent.status, "sent")
        self.assertEqual(sent.telegram_message_id, "777")
        self.assertEqual(uncertain.status, "uncertain")
