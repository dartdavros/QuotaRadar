from io import StringIO
from datetime import timedelta
from unittest.mock import Mock, patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from django.utils import timezone

from apps.telegram.client import TelegramAuthenticationError, TelegramPermanentChatError, TelegramTemporaryError
from apps.telegram.models import DeliveryTarget, DeliveryTargetType, PrivateChatRetirementNotice


@patch("apps.telegram.management.commands.announce_private_retirement.time.sleep")
@patch("apps.telegram.management.commands.announce_private_retirement.TelegramBotApiClient")
class RetirementCommandTests(TestCase):
    def setUp(self):
        for chat_id, enabled in (("111", True), ("222", False)):
            DeliveryTarget.objects.create(
                target_type=DeliveryTargetType.PRIVATE_CHAT, telegram_chat_id=chat_id, enabled=enabled,
            )
        DeliveryTarget.objects.create(target_type=DeliveryTargetType.CHANNEL, telegram_chat_id="-100123")

    def test_default_is_read_only_preview(self, client_class, sleep):
        output = StringIO()
        call_command("announce_private_retirement", stdout=output)
        self.assertIn("Private recipients: 2", output.getvalue())
        self.assertIn("pending=2", output.getvalue())
        self.assertFalse(PrivateChatRetirementNotice.objects.exists())
        client_class.assert_not_called()

    def test_send_continues_after_blocked_user_and_resume_does_not_repeat(self, client_class, sleep):
        client = Mock()
        client.send_message.side_effect = [TelegramPermanentChatError("Blocked."), "777"]
        client_class.return_value.__enter__.return_value = client
        output = StringIO()
        call_command("announce_private_retirement", send=True, stdout=output)
        call_command("announce_private_retirement", send=True, stdout=output)
        self.assertEqual([call.kwargs["chat_id"] for call in client.send_message.call_args_list], ["111", "222"])
        self.assertIn("sent=1, unreachable=1", output.getvalue())
        self.assertEqual(PrivateChatRetirementNotice.objects.count(), 2)

    def test_authentication_failure_aborts_before_other_users(self, client_class, sleep):
        client = Mock()
        client.send_message.side_effect = TelegramAuthenticationError("Invalid token.")
        client_class.return_value.__enter__.return_value = client
        with self.assertRaises(CommandError):
            call_command("announce_private_retirement", send=True, stdout=StringIO())
        self.assertEqual(client.send_message.call_count, 1)
        self.assertEqual(PrivateChatRetirementNotice.objects.count(), 1)

    def test_rate_limit_waits_then_finishes_remaining_users(self, client_class, sleep):
        client = Mock()
        client.send_message.side_effect = [
            TelegramTemporaryError("Rate limited.", retry_after=11, delivery_uncertain=False),
            "777", "778",
        ]
        client_class.return_value.__enter__.return_value = client
        clock = [timezone.now()]
        sleep.side_effect = lambda seconds: clock.__setitem__(0, clock[0] + timedelta(seconds=seconds))
        with patch("apps.telegram.retirement_delivery.timezone.now", side_effect=lambda: clock[0]):
            call_command("announce_private_retirement", send=True, stdout=StringIO())

        self.assertIn(11, [call.args[0] for call in sleep.call_args_list])
        self.assertEqual(client.send_message.call_count, 3)
        self.assertEqual(PrivateChatRetirementNotice.objects.filter(status="sent").count(), 2)
