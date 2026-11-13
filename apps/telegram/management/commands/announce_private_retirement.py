"""Preview or explicitly send the approved private-alert retirement notice."""

import time

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Count
from django.utils import timezone

from apps.telegram.client import TelegramApiError, TelegramBotApiClient
from apps.telegram.models import PrivateChatRetirementNotice, RetirementNoticeStatus as Status
from apps.telegram.retirement import RETIREMENT_MESSAGE
from apps.telegram.retirement_delivery import private_recipients, send_retirement_notice


class Command(BaseCommand):
    help = "Preview the private-recipient announcement; --send performs real Telegram sends."

    def add_arguments(self, parser):
        parser.add_argument("--send", action="store_true", help="Send to all saved private recipients.")

    def handle(self, *args, **options):
        self.stdout.write(RETIREMENT_MESSAGE)
        self._summary()
        if not options["send"]:
            self.stdout.write("Preview only. No data changed or messages sent. Use --send to deliver.")
            return
        try:
            with TelegramBotApiClient() as client:
                for target_id in private_recipients().order_by("pk").values_list("pk", flat=True).iterator():
                    self._send_recipient(target_id, client)
        except TelegramApiError as exc:
            raise CommandError(str(exc)) from None
        finally:
            self._summary()

    def _send_recipient(self, target_id, client):
        for _ in range(3):
            notice = PrivateChatRetirementNotice.objects.filter(target_id=target_id).first()
            if notice and notice.status == Status.PENDING and notice.next_attempt_at:
                remaining = max(0, (notice.next_attempt_at - timezone.now()).total_seconds())
                self.stdout.write(f"Telegram retry_after: waiting {remaining:.0f}s.")
                time.sleep(remaining)
            status = send_retirement_notice(target_id=target_id, client=client)
            if status != Status.PENDING:
                if status != "skipped":
                    time.sleep(0.1)  # At most ten requests per second in this command.
                return
        raise CommandError("Telegram still rate-limits sends. Retry --send later; saved outcomes are preserved.")

    def _summary(self):
        recipients = private_recipients()
        counts = dict(
            PrivateChatRetirementNotice.objects.filter(target__in=recipients)
            .values_list("status").annotate(total=Count("pk"))
        )
        total = recipients.count()
        counts[Status.PENDING] = counts.get(Status.PENDING, 0) + total - sum(counts.values())
        self.stdout.write(f"Private recipients: {total}. " + ", ".join(
            f"{status}={counts.get(status, 0)}" for status in Status.values
        ))
