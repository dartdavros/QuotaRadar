from unittest.mock import Mock

from django.test import TestCase

from apps.telegram.bot import TelegramBotRunner
from apps.telegram.client import TelegramUpdate
from apps.telegram.models import DeliveryTarget


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

    def test_start_stop_and_status_are_idempotent(self) -> None:
        self.runner.handle_update(self.update("/start"))
        self.runner.handle_update(self.update("/start@QuotaRadarBot"))
        self.runner.handle_update(self.update("/status"))
        self.runner.handle_update(self.update("/stop"))
        self.runner.handle_update(self.update("/stop"))

        self.assertEqual(DeliveryTarget.objects.count(), 1)
        self.assertFalse(DeliveryTarget.objects.get().enabled)
        replies = [
            call.kwargs["text"] for call in self.client.send_message.call_args_list
        ]
        self.assertEqual(replies[0], "Уведомления QuotaRadar включены.")
        self.assertEqual(replies[2], "Уведомления QuotaRadar включены.")
        self.assertEqual(replies[-1], "Уведомления QuotaRadar отключены.")

    def test_non_private_chat_is_ignored(self) -> None:
        update = TelegramUpdate(
            update_id=2,
            chat_id="-100123",
            chat_type="channel",
            text="/start",
        )

        self.runner.handle_update(update)

        self.assertFalse(DeliveryTarget.objects.exists())
        self.client.send_message.assert_not_called()
