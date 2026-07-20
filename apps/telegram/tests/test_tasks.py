from contextlib import contextmanager
from unittest.mock import Mock, patch

from django.test import TestCase

from apps.configuration.models import SystemConfiguration
from apps.telegram.client import (
    TelegramPermanentChatError,
    TelegramTemporaryError,
)
from apps.telegram.models import (
    Delivery,
    DeliveryStatus,
    DeliveryTarget,
    DeliveryTargetType,
)
from apps.telegram.tasks import deliver_analysis

from .helpers import create_relevant_analysis


@contextmanager
def acquired_lock(delivery_id: int):
    yield True


@contextmanager
def rejected_lock(delivery_id: int):
    yield False


class DeliverAnalysisTaskTests(TestCase):
    def setUp(self) -> None:
        self.analysis = create_relevant_analysis()
        self.target = DeliveryTarget.objects.create(
            target_type=DeliveryTargetType.PRIVATE_CHAT,
            telegram_chat_id="12345",
        )
        self.delivery = Delivery.objects.create(
            analysis=self.analysis,
            target=self.target,
        )
        configuration = SystemConfiguration.load()
        configuration.retry_count = 2
        configuration.save()

    @patch("apps.telegram.tasks.delivery_send_lock", acquired_lock)
    @patch("apps.telegram.tasks.TelegramBotApiClient")
    def test_success_is_not_sent_twice(self, client_class: Mock) -> None:
        client = Mock()
        client.send_message.return_value = "777"
        client_class.return_value.__enter__.return_value = client

        first = deliver_analysis.run(self.analysis.pk, self.target.pk)
        second = deliver_analysis.run(self.analysis.pk, self.target.pk)

        self.assertEqual(first["status"], "sent")
        self.assertEqual(second["status"], "already_sent")
        client.send_message.assert_called_once()
        self.delivery.refresh_from_db()
        self.assertEqual(self.delivery.status, DeliveryStatus.SENT)
        self.assertEqual(self.delivery.attempts, 1)
        self.assertEqual(self.delivery.telegram_message_id, "777")

    @patch("apps.telegram.tasks.delivery_send_lock", rejected_lock)
    @patch("apps.telegram.tasks.TelegramBotApiClient")
    def test_parallel_delivery_is_skipped(self, client_class: Mock) -> None:
        result = deliver_analysis.run(self.analysis.pk, self.target.pk)

        self.assertEqual(result["status"], "locked")
        client_class.assert_not_called()

    @patch("apps.telegram.tasks.delivery_send_lock", acquired_lock)
    @patch("apps.telegram.tasks.TelegramBotApiClient")
    def test_temporary_error_requests_retry(self, client_class: Mock) -> None:
        client = Mock()
        client.send_message.side_effect = TelegramTemporaryError(
            "Telegram API is temporarily unavailable.",
            retry_after=11,
        )
        client_class.return_value.__enter__.return_value = client

        with patch.object(
            deliver_analysis,
            "retry",
            side_effect=RuntimeError("retry requested"),
        ) as retry:
            with self.assertRaisesRegex(RuntimeError, "retry requested"):
                deliver_analysis.run(self.analysis.pk, self.target.pk)

        self.assertEqual(retry.call_args.kwargs["countdown"], 11)
        self.delivery.refresh_from_db()
        self.assertEqual(self.delivery.status, DeliveryStatus.FAILED)
        self.assertEqual(self.delivery.attempts, 1)

    @patch("apps.telegram.tasks.delivery_send_lock", acquired_lock)
    @patch("apps.telegram.tasks.TelegramBotApiClient")
    def test_permanent_private_chat_error_disables_target(
        self, client_class: Mock
    ) -> None:
        client = Mock()
        client.send_message.side_effect = TelegramPermanentChatError(
            "Telegram chat is unavailable or rejected the bot."
        )
        client_class.return_value.__enter__.return_value = client

        result = deliver_analysis.run(self.analysis.pk, self.target.pk)

        self.assertEqual(result["status"], "failed")
        self.target.refresh_from_db()
        self.assertFalse(self.target.enabled)

    @patch("apps.telegram.tasks.delivery_send_lock", acquired_lock)
    @patch("apps.telegram.tasks.TelegramBotApiClient")
    def test_permanent_channel_error_keeps_target_enabled(
        self, client_class: Mock
    ) -> None:
        self.target.target_type = DeliveryTargetType.CHANNEL
        self.target.telegram_chat_id = "@quota_radar"
        self.target.save()
        client = Mock()
        client.send_message.side_effect = TelegramPermanentChatError(
            "Telegram chat is unavailable or rejected the bot."
        )
        client_class.return_value.__enter__.return_value = client

        deliver_analysis.run(self.analysis.pk, self.target.pk)

        self.target.refresh_from_db()
        self.assertTrue(self.target.enabled)
