from unittest.mock import patch

from django.test import TestCase

from apps.telegram.models import (
    Delivery,
    DeliveryStatus,
    DeliveryTarget,
    DeliveryTargetType,
)
from apps.telegram.services import (
    format_delivery_message,
    queue_analysis_deliveries,
    requeue_failed_deliveries,
)

from .helpers import create_relevant_analysis


class DeliveryServiceTests(TestCase):
    def test_message_uses_server_owned_source_url(self) -> None:
        analysis = create_relevant_analysis()

        message = format_delivery_message(analysis)

        self.assertEqual(
            message,
            "Codex: повышены лимиты\n\n"
            "OpenAI временно увеличила лимиты Codex на 50%.\n\n"
            "Источник: https://x.com/OpenAIDevs/status/5001",
        )

    def test_fan_out_creates_one_task_per_enabled_target(self) -> None:
        analysis = create_relevant_analysis()
        active_channel = DeliveryTarget.objects.create(
            target_type=DeliveryTargetType.CHANNEL,
            telegram_chat_id="@quota_radar",
        )
        active_private = DeliveryTarget.objects.create(
            target_type=DeliveryTargetType.PRIVATE_CHAT,
            telegram_chat_id="12345",
        )
        DeliveryTarget.objects.create(
            target_type=DeliveryTargetType.PRIVATE_CHAT,
            telegram_chat_id="67890",
            enabled=False,
        )

        with patch("apps.telegram.tasks.deliver_analysis.delay") as delay:
            with self.captureOnCommitCallbacks(execute=True):
                first = queue_analysis_deliveries(analysis.pk)
            with self.captureOnCommitCallbacks(execute=True):
                second = queue_analysis_deliveries(analysis.pk)

        self.assertEqual(len(first.delivery_ids), 2)
        self.assertEqual(second.delivery_ids, ())
        self.assertEqual(Delivery.objects.count(), 2)
        self.assertEqual(
            {call.args for call in delay.call_args_list},
            {
                (analysis.pk, active_channel.pk),
                (analysis.pk, active_private.pk),
            },
        )

    def test_permanently_failed_delivery_is_not_queued_again(self) -> None:
        analysis = create_relevant_analysis(external_id="5002")
        target = DeliveryTarget.objects.create(
            target_type=DeliveryTargetType.CHANNEL,
            telegram_chat_id="@quota_retry",
        )
        Delivery.objects.create(
            analysis=analysis,
            target=target,
            status="failed",
            last_error="Delivery task could not be queued.",
        )

        with patch("apps.telegram.tasks.deliver_analysis.delay") as delay:
            with self.captureOnCommitCallbacks(execute=True):
                queued = queue_analysis_deliveries(analysis.pk)

        self.assertEqual(queued.delivery_ids, ())
        delay.assert_not_called()

    def test_broker_publish_failure_is_recorded_without_raising(self) -> None:
        analysis = create_relevant_analysis(external_id="5003")
        target = DeliveryTarget.objects.create(
            target_type=DeliveryTargetType.CHANNEL,
            telegram_chat_id="@quota_broker",
        )

        with patch(
            "apps.telegram.tasks.deliver_analysis.delay",
            side_effect=RuntimeError("broker details must not be persisted"),
        ):
            with self.captureOnCommitCallbacks(execute=True):
                queue_analysis_deliveries(analysis.pk)

        delivery = Delivery.objects.get(analysis=analysis, target=target)
        self.assertEqual(delivery.status, "pending")
        self.assertEqual(delivery.last_error, "Delivery task could not be queued.")


class DeliveryRequeueServiceTests(TestCase):
    def setUp(self) -> None:
        self.analysis = create_relevant_analysis(external_id="requeue-5001")
        self.target = DeliveryTarget.objects.create(
            target_type=DeliveryTargetType.CHANNEL,
            telegram_chat_id="@quota_requeue",
        )
        self.delivery = Delivery.objects.create(
            analysis=self.analysis,
            target=self.target,
            status=DeliveryStatus.FAILED,
            attempts=2,
            last_error="Permanent delivery error.",
        )

    @patch("apps.telegram.tasks.deliver_analysis.delay")
    def test_requeue_resets_failed_delivery_and_dispatches_new_task(self, delay) -> None:
        result = requeue_failed_deliveries(delivery_ids=(self.delivery.pk,))

        self.assertEqual(result.requested, 1)
        self.assertEqual(result.queued, 1)
        self.assertEqual(result.skipped, 0)
        self.assertEqual(result.dispatch_failed, 0)
        delay.assert_called_once_with(self.analysis.pk, self.target.pk)
        self.delivery.refresh_from_db()
        self.assertEqual(self.delivery.status, DeliveryStatus.PENDING)
        self.assertEqual(self.delivery.attempts, 0)
        self.assertEqual(self.delivery.last_error, "")

    @patch(
        "apps.telegram.tasks.deliver_analysis.delay",
        side_effect=RuntimeError("broker unavailable"),
    )
    def test_dispatch_failure_restores_failed_delivery(self, delay) -> None:
        result = requeue_failed_deliveries(delivery_ids=(self.delivery.pk,))

        self.assertEqual(result.queued, 0)
        self.assertEqual(result.dispatch_failed, 1)
        self.delivery.refresh_from_db()
        self.assertEqual(self.delivery.status, DeliveryStatus.FAILED)
        self.assertEqual(self.delivery.attempts, 2)
        self.assertEqual(self.delivery.last_error, "Permanent delivery error.")

    @patch("apps.telegram.tasks.deliver_analysis.delay")
    def test_non_failed_delivery_is_skipped(self, delay) -> None:
        self.delivery.status = DeliveryStatus.SENT
        self.delivery.telegram_message_id = "777"
        self.delivery.save(
            update_fields=("status", "telegram_message_id", "updated_at")
        )

        result = requeue_failed_deliveries(delivery_ids=(self.delivery.pk,))

        self.assertEqual(result.queued, 0)
        self.assertEqual(result.skipped, 1)
        delay.assert_not_called()

