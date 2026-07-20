"""Long-polling Telegram command processor."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable

from .client import (
    TelegramApiError,
    TelegramBotApiClient,
    TelegramTemporaryError,
    TelegramUpdate,
)
from .subscriptions import (
    SubscriptionConflictError,
    disable_private_chat,
    enable_private_chat,
    get_private_chat_status,
)

logger = logging.getLogger(__name__)

_START_ENABLED = "Уведомления QuotaRadar включены."
_STOP_DISABLED = "Уведомления QuotaRadar отключены."
_STATUS_ENABLED = "Уведомления QuotaRadar включены."
_STATUS_DISABLED = "Уведомления QuotaRadar отключены."
_SUBSCRIPTION_ERROR = "Не удалось изменить подписку QuotaRadar."


class TelegramBotRunner:
    """Stateful process loop with process-local idempotent update offset."""

    def __init__(
        self,
        *,
        client: TelegramBotApiClient,
        poll_timeout_seconds: int = 30,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if poll_timeout_seconds <= 0:
            raise ValueError("poll_timeout_seconds must be greater than zero.")
        self._client = client
        self._poll_timeout_seconds = poll_timeout_seconds
        self._sleep = sleep
        self._offset: int | None = None

    def run(self, *, should_stop: Callable[[], bool]) -> None:
        retry_delay = 1.0
        while not should_stop():
            try:
                updates = self._client.get_updates(
                    offset=self._offset,
                    timeout_seconds=self._poll_timeout_seconds,
                )
                retry_delay = 1.0
            except TelegramTemporaryError as exc:
                delay = float(exc.retry_after or retry_delay)
                logger.warning("Temporary Telegram polling failure; retrying.")
                self._sleep(delay)
                retry_delay = min(retry_delay * 2, 60.0)
                continue

            for update in updates:
                self._offset = update.update_id + 1
                self.handle_update(update)

    def handle_update(self, update: TelegramUpdate) -> None:
        if update.chat_type != "private":
            return
        command = _extract_command(update.text)
        if command is None:
            return
        try:
            reply = _execute_command(command=command, chat_id=update.chat_id)
        except SubscriptionConflictError:
            reply = _SUBSCRIPTION_ERROR
        if reply is None:
            return
        try:
            self._client.send_message(chat_id=update.chat_id, text=reply)
        except TelegramApiError:
            logger.warning(
                "Telegram command reply failed for chat_id=%s.", update.chat_id
            )


def _extract_command(text: str) -> str | None:
    token = text.strip().split(maxsplit=1)[0] if text.strip() else ""
    if not token.startswith("/"):
        return None
    return token.split("@", maxsplit=1)[0].casefold()


def _execute_command(*, command: str, chat_id: str) -> str | None:
    if command == "/start":
        enable_private_chat(chat_id)
        return _START_ENABLED
    if command == "/stop":
        disable_private_chat(chat_id)
        return _STOP_DISABLED
    if command == "/status":
        status = get_private_chat_status(chat_id)
        return _STATUS_ENABLED if status.enabled else _STATUS_DISABLED
    return None
