from unittest.mock import patch

from celery.exceptions import Retry

from apps.advertising.models import Placement, PlacementStatus
from apps.advertising.services import begin_send, prepare_delivery
from apps.telegram.client import TelegramPermanentChatError, TelegramResponseError, TelegramTemporaryError
from apps.telegram.models import DeliveryStatus
from apps.telegram.tasks import deliver_analysis
from apps.telegram.tests.test_tasks import acquired_lock
from .base import AdvertisingTestCase


@patch("apps.telegram.tasks.delivery_send_lock", acquired_lock)
class AdvertisingSendingTests(AdvertisingTestCase):
    @patch("apps.telegram.tasks.TelegramBotApiClient")
    def test_custom_emoji_rejection_never_replaces_requested_emoji(self, client_class):
        self.campaign.body = "🤖[5397681122542893003] [**Купить**](https://example.com)"
        self.campaign.save()
        client = client_class.return_value.__enter__.return_value
        client.send_message.side_effect = TelegramPermanentChatError("Unsupported custom emoji")
        self.assertEqual(deliver_analysis.run(self.delivery.analysis_id, self.target.pk)["status"], "failed")
        client.send_message.assert_called_once()
        self.assertTrue(any(entity["type"] == "custom_emoji" for entity in
                            client.send_message.call_args.kwargs["entities"]))
        self.delivery.refresh_from_db()
        self.assertTrue(any(entity["type"] == "custom_emoji" for entity in self.delivery.message_entities))
        self.assertEqual(self.campaign.sent_posts, 0)
        self.assertEqual(self.campaign.reserved_posts, 0)

    @patch("apps.telegram.tasks.TelegramBotApiClient")
    def test_success_sends_entities_and_counts_once(self, client_class):
        client = client_class.return_value.__enter__.return_value
        client.send_message.return_value = "101"
        self.assertEqual(deliver_analysis.run(self.delivery.analysis_id, self.target.pk)["status"], "sent")
        self.assertEqual(deliver_analysis.run(self.delivery.analysis_id, self.target.pk)["status"], "already_sent")
        client.send_message.assert_called_once()
        kwargs = client.send_message.call_args.kwargs
        links = [entity for entity in kwargs["entities"] if entity["type"] == "text_link"]
        self.assertEqual(len(links), 1)
        source = next(entity for entity in kwargs["entities"] if entity["type"] == "url")
        encoded = kwargs["text"].encode("utf-16-le")
        visible_source = encoded[source["offset"] * 2:(source["offset"] + source["length"]) * 2].decode("utf-16-le")
        self.assertEqual(visible_source, self.delivery.analysis.source_post.source_url)
        self.assertIn("Рекомендация: ", kwargs["text"])
        self.assertEqual(self.campaign.sent_posts, 1)

    @patch("apps.telegram.tasks.TelegramBotApiClient")
    def test_network_failure_stops_for_manual_check(self, client_class):
        client = client_class.return_value.__enter__.return_value
        client.send_message.side_effect = TelegramTemporaryError("Network timeout")
        self.assertEqual(deliver_analysis.run(self.delivery.analysis_id, self.target.pk)["status"], "uncertain")
        self.assertEqual(deliver_analysis.run(self.delivery.analysis_id, self.target.pk)["status"], "uncertain")
        client.send_message.assert_called_once()
        self.assertEqual(self.campaign.sent_posts, 0)
        self.assertEqual(self.campaign.reserved_posts, 1)

    @patch("apps.telegram.tasks.TelegramBotApiClient")
    def test_invalid_receipt_is_not_retried(self, client_class):
        client_class.return_value.__enter__.return_value.send_message.side_effect = TelegramResponseError("No message ID")
        self.assertEqual(deliver_analysis.run(self.delivery.analysis_id, self.target.pk)["status"], "uncertain")

    @patch("apps.telegram.tasks.TelegramBotApiClient")
    def test_429_can_retry_same_payload(self, client_class):
        client_class.return_value.__enter__.return_value.send_message.side_effect = TelegramTemporaryError(
            "Rate limited", retry_after=10, delivery_uncertain=False)
        with patch.object(deliver_analysis, "retry", side_effect=Retry("retry")), self.assertRaises(Retry):
            deliver_analysis.run(self.delivery.analysis_id, self.target.pk)
        self.delivery.refresh_from_db()
        self.assertEqual(self.delivery.status, DeliveryStatus.PENDING)
        self.assertEqual(Placement.objects.get(delivery=self.delivery).status, PlacementStatus.RESERVED)

    @patch("apps.telegram.tasks.TelegramBotApiClient")
    def test_permanent_rejection_releases_slot(self, client_class):
        client_class.return_value.__enter__.return_value.send_message.side_effect = TelegramPermanentChatError("Rejected")
        self.assertEqual(deliver_analysis.run(self.delivery.analysis_id, self.target.pk)["status"], "failed")
        self.assertEqual(self.campaign.reserved_posts, 0)

    @patch("apps.telegram.tasks.TelegramBotApiClient")
    def test_recovered_inflight_request_never_sends_again(self, client_class):
        prepare_delivery(self.delivery, "Новость")
        begin_send(self.delivery.pk)
        self.assertEqual(deliver_analysis.run(self.delivery.analysis_id, self.target.pk)["status"], "uncertain")
        client_class.assert_not_called()
