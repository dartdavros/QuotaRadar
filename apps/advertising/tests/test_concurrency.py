from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest import skipUnless

from django.db import close_old_connections, connection
from django.test import TransactionTestCase
from django.utils import timezone

from apps.advertising.models import Campaign, Placement
from apps.advertising.services import prepare_delivery
from apps.telegram.models import Delivery, DeliveryTarget, DeliveryTargetType
from apps.telegram.tests.helpers import create_relevant_analysis


@skipUnless(connection.vendor == "postgresql", "Campaign reservations require PostgreSQL row locks.")
class CampaignConcurrencyTests(TransactionTestCase):
    serialized_rollback = True

    def test_two_workers_cannot_reserve_the_last_slot_twice(self):
        target = DeliveryTarget.objects.create(target_type=DeliveryTargetType.CHANNEL, telegram_chat_id="@concurrent_ads")
        Campaign.objects.create(target=target, message="Курс", link_label="Программа", url="https://example.com",
                                total_posts=1, enabled=True)
        deliveries = [Delivery.objects.create(target=target, analysis=create_relevant_analysis(
            external_id=f"concurrent-ad-{number}", published_at=timezone.now())) for number in range(2)]
        barrier = Barrier(2)

        def reserve(delivery_id):
            close_old_connections()
            try:
                delivery = Delivery.objects.get(pk=delivery_id)
                barrier.wait(timeout=10)
                return prepare_delivery(delivery, "Новость")
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as workers:
            results = list(workers.map(reserve, [delivery.pk for delivery in deliveries]))
        self.assertEqual(Placement.objects.count(), 1)
        self.assertEqual(sum(bool(entities) for _, entities in results), 1)
