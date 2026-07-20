from unittest.mock import Mock, patch

from django.test import SimpleTestCase

from apps.telegram.client import (
    TelegramBotApiClient,
    TelegramPermanentChatError,
    TelegramTemporaryError,
)


class TelegramBotApiClientTests(SimpleTestCase):
    def setUp(self) -> None:
        self.http_client = Mock()
        self.client = TelegramBotApiClient(
            http_client=self.http_client,
            token="test-token",
        )

    def response(self, *, status_code: int, payload: object) -> Mock:
        response = Mock(status_code=status_code)
        response.json.return_value = payload
        return response

    def test_get_updates_parses_private_message(self) -> None:
        self.http_client.post.return_value = self.response(
            status_code=200,
            payload={
                "ok": True,
                "result": [
                    {
                        "update_id": 101,
                        "message": {
                            "text": "/start",
                            "chat": {"id": 42, "type": "private"},
                        },
                    }
                ],
            },
        )

        updates = self.client.get_updates(offset=100, timeout_seconds=30)

        self.assertEqual(len(updates), 1)
        self.assertEqual(updates[0].chat_id, "42")
        self.assertEqual(updates[0].text, "/start")
        payload = self.http_client.post.call_args.kwargs["json"]
        self.assertEqual(payload["offset"], 100)
        self.assertEqual(payload["timeout"], 30)

    def test_send_message_returns_message_id(self) -> None:
        self.http_client.post.return_value = self.response(
            status_code=200,
            payload={"ok": True, "result": {"message_id": 777}},
        )

        message_id = self.client.send_message(chat_id="42", text="Сообщение")

        self.assertEqual(message_id, "777")
        payload = self.http_client.post.call_args.kwargs["json"]
        self.assertEqual(payload["chat_id"], "42")
        self.assertTrue(payload["disable_web_page_preview"])

    def test_rate_limit_exposes_safe_retry_after(self) -> None:
        self.http_client.post.return_value = self.response(
            status_code=429,
            payload={
                "ok": False,
                "error_code": 429,
                "description": "Too Many Requests",
                "parameters": {"retry_after": 17},
            },
        )

        with self.assertRaises(TelegramTemporaryError) as raised:
            self.client.send_message(chat_id="42", text="Сообщение")

        self.assertEqual(raised.exception.retry_after, 17)

    def test_unavailable_chat_is_permanent_error(self) -> None:
        self.http_client.post.return_value = self.response(
            status_code=403,
            payload={
                "ok": False,
                "error_code": 403,
                "description": "Forbidden: bot was blocked by the user",
            },
        )

        with self.assertRaises(TelegramPermanentChatError):
            self.client.send_message(chat_id="42", text="Сообщение")

    @patch("apps.telegram.client.get_secret", return_value="telegram-token")
    @patch("apps.telegram.client.create_http_client")
    def test_default_client_uses_shared_proxy_factory(
        self,
        create_http_client: Mock,
        get_secret: Mock,
    ) -> None:
        TelegramBotApiClient()

        get_secret.assert_called_once()
        create_http_client.assert_called_once_with(timeout_seconds=30)
