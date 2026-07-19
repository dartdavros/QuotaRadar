"""Stage-one Telegram process without external API calls."""

from __future__ import annotations

import logging
import signal
from argparse import ArgumentParser
from threading import Event
from types import FrameType
from typing import Any

from django.core.management.base import BaseCommand

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Run the stage-one Telegram process without external requests."
    requires_system_checks: list[str] = []

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument(
            "--sleep-seconds",
            type=float,
            default=30.0,
            help="Idle wait interval used while Telegram integration is not implemented.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        sleep_seconds = options["sleep_seconds"]
        if sleep_seconds <= 0:
            raise ValueError("--sleep-seconds must be greater than zero.")

        stop_event = Event()

        def request_stop(signum: int, _frame: FrameType | None) -> None:
            logger.info("Telegram process received signal %s; shutting down.", signum)
            stop_event.set()

        signal.signal(signal.SIGTERM, request_stop)
        signal.signal(signal.SIGINT, request_stop)

        logger.info(
            "Telegram process started in stage-one idle mode; external requests are disabled."
        )
        while not stop_event.wait(timeout=sleep_seconds):
            pass
        logger.info("Telegram process stopped.")
