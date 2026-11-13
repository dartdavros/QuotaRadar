from unittest.mock import Mock

from django.test import TestCase

from apps.telegram.bot import TelegramBotRunner
from apps.telegram.client import TelegramUpdate
from apps.telegram.models import DeliveryTarget, DeliveryTargetType
from apps.telegram.retirement import RETIREMENT_MESSAGE


class TelegramBotRunnerTests(TestCase):
    def setUp(self) -> None:
        self.client = Mock()
        self.runner = TelegramBotRunner(client=self.client)

    def update(self, text: str) -> TelegramUpdate:
        return TelegramUpdate(
            update_id=1,
            chat_id="12345",
            chat_type="private",
            text=text,
        )

    def test_commands_redirect_to_channel_without_creating_subscriptions(self) -> None:
        self.runner.handle_update(self.update("/start"))
        self.runner.handle_update(self.update("/start@QuotaRadarBot"))
        self.runner.handle_update(self.update("/status"))
        self.runner.handle_update(self.update("/stop"))
        self.runner.handle_update(self.update("/stop"))

        self.assertFalse(DeliveryTarget.objects.exists())
        replies = [
            call.kwargs["text"] for call in self.client.send_message.call_args_list
        ]
        self.assertEqual(replies, [RETIREMENT_MESSAGE] * 5)

    def test_start_cannot_reactivate_old_subscription(self) -> None:
        target = DeliveryTarget.objects.create(
            target_type=DeliveryTargetType.PRIVATE_CHAT, telegram_chat_id="12345", enabled=False,
        )
        self.runner.handle_update(self.update("/start"))
        target.refresh_from_db()
        self.assertFalse(target.enabled)

    def test_non_private_chat_is_ignored(self) -> None:
        for chat_type in ("group", "supergroup", "channel"):
            self.runner.handle_update(TelegramUpdate(
                update_id=2, chat_id="-100123", chat_type=chat_type, text="/start",
            ))

        self.assertFalse(DeliveryTarget.objects.exists())
        self.client.send_message.assert_not_called()
