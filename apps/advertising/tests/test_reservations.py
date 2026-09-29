from django.core.exceptions import ValidationError

from apps.advertising.models import Placement, PlacementStatus
from apps.advertising.services import prepare_delivery, begin_send, mark_uncertain, resolve_placement
from apps.telegram.delivery_state import mark_failed, mark_sent
from apps.telegram.models import DeliveryStatus, DeliveryTarget, DeliveryTargetType
from .base import AdvertisingTestCase


class ReservationTests(AdvertisingTestCase):
    def test_only_link_label_is_explicitly_linked_and_offsets_support_emoji(self):
        text, entities = prepare_delivery(self.delivery, "Новость 😀")
        self.assertEqual(text, "Новость 😀\n\nРекомендация: Курс по AI для разработчиков. Программа")
        encoded = text.encode("utf-16-le")
        entity = entities[0]
        linked = encoded[entity["offset"] * 2:(entity["offset"] + entity["length"]) * 2].decode("utf-16-le")
        self.assertEqual(linked, "Программа")
        self.assertEqual(entity["type"], "text_link")

    def test_retries_freeze_post_url_and_copy(self):
        original = prepare_delivery(self.delivery, "Новость")
        self.campaign.message, self.campaign.url = "Изменённый текст", "https://example.com/other"
        self.campaign.save()
        self.assertEqual(prepare_delivery(self.delivery, "Другой пост"), original)
        self.assertEqual(Placement.objects.count(), 1)

    def test_reserved_slots_prevent_overbooking(self):
        prepare_delivery(self.delivery, "Первый пост")
        prepare_delivery(self.make_delivery("ads-2"), "Второй пост")
        self.assertEqual(prepare_delivery(self.make_delivery("ads-3"), "Третий пост"), ("Третий пост", []))
        self.assertEqual(self.campaign.sent_posts, 0)
        self.assertEqual(self.campaign.reserved_posts, 2)
        self.assertEqual(self.campaign.remaining_posts, 2)

    def test_success_counts_once_and_completes_campaign(self):
        prepare_delivery(self.delivery, "Первый")
        second = self.make_delivery("ads-2")
        prepare_delivery(second, "Второй")
        mark_sent(self.delivery.pk, "101")
        mark_sent(self.delivery.pk, "101")
        self.assertEqual(self.campaign.sent_posts, 1)
        mark_sent(second.pk, "102")
        self.campaign.refresh_from_db()
        self.assertFalse(self.campaign.enabled)
        self.assertEqual(self.campaign.remaining_posts, 0)

    def test_rejection_releases_slot_but_old_retry_cannot_overbook(self):
        self.campaign.total_posts = 1
        self.campaign.save()
        prepare_delivery(self.delivery, "Первый")
        mark_failed(self.delivery.pk, "Отклонено Telegram")
        prepare_delivery(self.make_delivery("ads-2"), "Другой пост")
        with self.assertRaisesRegex(ValueError, "свободного размещения"):
            prepare_delivery(self.delivery, "Первый")

    def test_pause_stops_new_assignments_and_preserves_retry(self):
        original = prepare_delivery(self.delivery, "Первый")
        self.campaign.enabled = False
        self.campaign.save()
        self.assertEqual(prepare_delivery(self.make_delivery("ads-2"), "Второй"), ("Второй", []))
        self.assertEqual(prepare_delivery(self.delivery, "Изменённый пост"), original)

    def test_private_notifications_never_get_advertising(self):
        private = DeliveryTarget.objects.create(target_type=DeliveryTargetType.PRIVATE_CHAT, telegram_chat_id="12345")
        delivery = self.make_delivery("ads-private", private)
        self.assertEqual(prepare_delivery(delivery, "Новость"), ("Новость", []))

    def test_reserve_full_allowance_and_do_not_truncate(self):
        prepare_delivery(self.delivery, "я" * 3894)
        with self.assertRaisesRegex(ValueError, "3894"):
            prepare_delivery(self.make_delivery("ads-long"), "я" * 3895)
        self.assertEqual(Placement.objects.count(), 1)

    def test_total_cannot_drop_below_held_placements(self):
        prepare_delivery(self.delivery, "Первый")
        prepare_delivery(self.make_delivery("ads-2"), "Второй")
        self.campaign.total_posts = 1
        with self.assertRaises(ValidationError):
            self.campaign.save()


class UncertainDeliveryTests(AdvertisingTestCase):
    def setUp(self):
        super().setUp()
        prepare_delivery(self.delivery, "Новость")
        begin_send(self.delivery.pk)

    def test_crashed_send_cannot_send_again(self):
        self.assertFalse(begin_send(self.delivery.pk))
        self.delivery.refresh_from_db()
        self.assertEqual(self.delivery.status, DeliveryStatus.UNCERTAIN)

    def test_manual_confirmation_requires_note_and_message_id(self):
        mark_uncertain(self.delivery.pk, "Неизвестно")
        placement = self.delivery.advertising
        with self.assertRaises(ValueError):
            resolve_placement(placement.pk, was_sent=True)
        placement.resolution_note = "Пост найден в канале."
        placement.save()
        with self.assertRaises(ValueError):
            resolve_placement(placement.pk, was_sent=True)
        placement.telegram_message_id = "101"
        placement.save()
        resolve_placement(placement.pk, was_sent=True)
        self.assertEqual(self.campaign.sent_posts, 1)
        self.delivery.refresh_from_db()
        self.assertEqual(self.delivery.telegram_message_id, "101")

    def test_confirmed_absence_releases_held_slot(self):
        mark_uncertain(self.delivery.pk, "Неизвестно")
        placement = self.delivery.advertising
        placement.resolution_note = "Проверил канал, пост отсутствует."
        placement.save()
        resolve_placement(placement.pk, was_sent=False)
        placement.refresh_from_db()
        self.assertEqual(placement.status, PlacementStatus.RELEASED)
        self.assertEqual(self.campaign.reserved_posts, 0)
