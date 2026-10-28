from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from apps.analysis.reset_alert import MAX_QUOTED_CHARACTERS, build_alert_text, send_reset_review_alert
from apps.configuration.models import SystemConfiguration
from apps.monitoring.models import MonitoringEvent, MonitoringEventStatus
from apps.sources.models import Source, SourcePost
from apps.telegram.client import TelegramTemporaryError

TEXT = "Day 23/ Much requested plugins. Just kidding, today is a reset."


class ResetAlertTests(TestCase):
    def setUp(self):
        self.source = Source.objects.get(username="thsottiaux")
        self.post = SourcePost.objects.create(
            source=self.source, external_id="2115273064481218829", text=TEXT,
            normalized_text=TEXT,
            source_url="https://x.com/thsottiaux/status/2115273064481218829",
            published_at=timezone.now(), raw_data={},
        )
        self.configuration = SystemConfiguration.load()

    def with_chat(self, chat_id):
        self.configuration.reset_alert_chat_id = chat_id
        self.configuration.save(update_fields=("reset_alert_chat_id",))

    def test_nothing_is_sent_while_no_alert_chat_is_configured(self):
        with patch("apps.analysis.reset_alert.TelegramBotApiClient") as client_class:
            sent = send_reset_review_alert(source_post=self.post, configuration=self.configuration)
        self.assertFalse(sent)
        client_class.assert_not_called()
        self.assertFalse(MonitoringEvent.objects.exists())

    def test_alert_quotes_the_publication_and_records_the_event(self):
        self.with_chat("-1001234567890")
        with patch("apps.analysis.reset_alert.TelegramBotApiClient") as client_class:
            client = client_class.return_value.__enter__.return_value
            sent = send_reset_review_alert(source_post=self.post, configuration=self.configuration)
        self.assertTrue(sent)
        kwargs = client.send_message.call_args.kwargs
        self.assertEqual(kwargs["chat_id"], "-1001234567890")
        self.assertIn(TEXT, kwargs["text"])
        self.assertIn(self.post.source_url, kwargs["text"])
        event = MonitoringEvent.objects.get()
        self.assertEqual(event.status, MonitoringEventStatus.SUCCESS)
        self.assertIn(self.post.external_id, event.message)

    def test_long_publication_is_truncated_in_the_alert(self):
        self.post.text = "Day 24/ " + "очень длинный текст. " * 40
        body = build_alert_text(self.post)
        quoted = body.split("\n\n", 1)[1]
        self.assertLessEqual(len(quoted), MAX_QUOTED_CHARACTERS + 1)
        self.assertTrue(quoted.endswith("…"))

    def test_telegram_failure_is_recorded_without_breaking_the_analysis(self):
        self.with_chat("@quotaradar_alerts")
        with patch("apps.analysis.reset_alert.TelegramBotApiClient") as client_class:
            client = client_class.return_value.__enter__.return_value
            client.send_message.side_effect = TelegramTemporaryError("Telegram API is temporarily unavailable.")
            sent = send_reset_review_alert(source_post=self.post, configuration=self.configuration)
        self.assertFalse(sent)
        event = MonitoringEvent.objects.get()
        self.assertEqual(event.status, MonitoringEventStatus.ERROR)
        self.assertEqual(event.error_type, "TelegramTemporaryError")
