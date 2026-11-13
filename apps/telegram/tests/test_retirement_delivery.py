from datetime import timedelta
from unittest.mock import Mock

from django.test import TestCase
from django.utils import timezone

from apps.telegram.client import (
    TelegramAuthenticationError, TelegramPermanentChatError,
    TelegramResponseError, TelegramTemporaryError,
)
from apps.telegram.models import (
    DeliveryTarget, DeliveryTargetType, PrivateChatRetirementNotice,
    RetirementNoticeStatus as Status,
)
from apps.telegram.retirement import RETIREMENT_MESSAGE
from apps.telegram.retirement_delivery import private_recipients, send_retirement_notice


class RetirementDeliveryTests(TestCase):
    def setUp(self):
        self.target = DeliveryTarget.objects.create(
            target_type=DeliveryTargetType.PRIVATE_CHAT, telegram_chat_id="12345", enabled=False,
        )
        self.client = Mock()
        self.client.send_message.return_value = "777"

    def send(self):
        return send_retirement_notice(target_id=self.target.pk, client=self.client)

    def test_disabled_subscriber_receives_approved_notice_once(self):
        self.assertEqual(self.send(), Status.SENT)
        self.assertEqual(self.send(), Status.SENT)
        self.client.send_message.assert_called_once_with(chat_id="12345", text=RETIREMENT_MESSAGE)
        notice = PrivateChatRetirementNotice.objects.get()
        self.assertEqual(notice.telegram_message_id, "777")
        self.assertIsNotNone(notice.sent_at)
        self.assertEqual(notice.attempts, 1)
        self.target.refresh_from_db()
        self.assertFalse(self.target.enabled)

    def test_groups_and_channels_are_excluded_even_if_mislabelled(self):
        channel = DeliveryTarget.objects.create(
            target_type=DeliveryTargetType.CHANNEL, telegram_chat_id="-100123",
        )
        group = DeliveryTarget.objects.create(
            target_type=DeliveryTargetType.CHANNEL, telegram_chat_id="-5678",
        )
        # Defensive check for legacy data bypassing model validation.
        DeliveryTarget.objects.filter(pk=group.pk).update(target_type=DeliveryTargetType.PRIVATE_CHAT)
        self.assertEqual(list(private_recipients()), [self.target])
        for target in (channel, group):
            self.assertEqual(send_retirement_notice(target_id=target.pk, client=self.client), "skipped")
        self.client.send_message.assert_not_called()
        self.assertFalse(PrivateChatRetirementNotice.objects.exists())

    def test_inflight_send_cannot_be_claimed_again(self):
        def in_flight(**kwargs):
            self.assertEqual(self.send(), Status.SENDING)
            return "778"

        self.client.send_message.side_effect = in_flight
        self.assertEqual(self.send(), Status.SENT)
        self.client.send_message.assert_called_once()

    def test_crashed_send_is_not_automatically_repeated(self):
        PrivateChatRetirementNotice.objects.create(target=self.target, status=Status.SENDING)
        self.assertEqual(self.send(), Status.SENDING)
        self.client.send_message.assert_not_called()

    def test_blocked_chat_is_recorded_and_never_retried(self):
        self.client.send_message.side_effect = TelegramPermanentChatError("Chat unavailable.")
        self.assertEqual(self.send(), Status.UNREACHABLE)
        self.assertEqual(self.send(), Status.UNREACHABLE)
        self.client.send_message.assert_called_once()

    def test_timeout_is_uncertain_and_never_automatically_retried(self):
        self.client.send_message.side_effect = TelegramTemporaryError("Timed out.")
        self.assertEqual(self.send(), Status.UNCERTAIN)
        self.assertEqual(self.send(), Status.UNCERTAIN)
        self.client.send_message.assert_called_once()

    def test_rate_limit_is_retried_only_after_retry_after(self):
        self.client.send_message.side_effect = TelegramTemporaryError(
            "Rate limited.", retry_after=11, delivery_uncertain=False,
        )
        self.assertEqual(self.send(), Status.PENDING)
        self.assertEqual(self.send(), Status.PENDING)
        self.client.send_message.assert_called_once()
        notice = PrivateChatRetirementNotice.objects.get()
        self.assertGreater(notice.next_attempt_at, timezone.now() + timedelta(seconds=10))
        PrivateChatRetirementNotice.objects.update(next_attempt_at=timezone.now() - timedelta(seconds=1))
        self.client.send_message.side_effect = None
        self.assertEqual(self.send(), Status.SENT)
        notice.refresh_from_db()
        self.assertEqual(notice.attempts, 2)
        self.assertIsNone(notice.next_attempt_at)

    def test_rejected_token_stops_run_but_allows_later_retry(self):
        self.client.send_message.side_effect = TelegramAuthenticationError("Invalid token.")
        with self.assertRaises(TelegramAuthenticationError):
            self.send()
        self.assertEqual(PrivateChatRetirementNotice.objects.get().status, Status.PENDING)

    def test_malformed_success_is_uncertain_and_stops_run(self):
        self.client.send_message.side_effect = TelegramResponseError("Missing message ID.")
        with self.assertRaises(TelegramResponseError):
            self.send()
        self.assertEqual(self.send(), Status.UNCERTAIN)
        self.client.send_message.assert_called_once()
