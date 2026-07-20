"""Run the Telegram long-polling process."""

from __future__ import annotations

import logging
import signal
from argparse import ArgumentParser
from threading import Event
from types import FrameType
from typing import Any

from django.core.management.base import BaseCommand, CommandError

from apps.telegram.bot import TelegramBotRunner
from apps.telegram.client import TelegramApiError, TelegramBotApiClient

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Run Telegram Bot API long polling for /start, /stop and /status."

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument(
            "--poll-timeout-seconds",
            type=int,
            default=30,
            help="Telegram getUpdates long-poll timeout.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        poll_timeout_seconds = options["poll_timeout_seconds"]
        if poll_timeout_seconds <= 0:
            raise CommandError("--poll-timeout-seconds must be greater than zero.")

        stop_event = Event()

        def request_stop(signum: int, _frame: FrameType | None) -> None:
            logger.info("Telegram process received signal %s; shutting down.", signum)
            stop_event.set()

        signal.signal(signal.SIGTERM, request_stop)
        signal.signal(signal.SIGINT, request_stop)

        try:
            with TelegramBotApiClient(
                timeout_seconds=poll_timeout_seconds + 10
            ) as client:
                runner = TelegramBotRunner(
                    client=client,
                    poll_timeout_seconds=poll_timeout_seconds,
                )
                logger.info("Telegram long-polling process started.")
                runner.run(should_stop=stop_event.is_set)
        except TelegramApiError as exc:
            raise CommandError(str(exc)) from None
        finally:
            logger.info("Telegram long-polling process stopped.")
