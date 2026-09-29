from django.test import TestCase
from django.utils import timezone

from apps.telegram.models import Delivery, DeliveryTarget, DeliveryTargetType
from apps.telegram.tests.helpers import create_relevant_analysis
from apps.advertising.models import Campaign


class AdvertisingTestCase(TestCase):
    def setUp(self):
        self.target = DeliveryTarget.objects.create(target_type=DeliveryTargetType.CHANNEL, telegram_chat_id="@quota_ads")
        self.campaign = Campaign.objects.create(target=self.target, message="Курс по AI для разработчиков.",
                                               link_label="Программа", url="https://example.com/course", total_posts=2, enabled=True)
        self.delivery = self.make_delivery("ads-1")

    def make_delivery(self, number, target=None):
        analysis = create_relevant_analysis(external_id=number, published_at=timezone.now())
        return Delivery.objects.create(analysis=analysis, target=target or self.target)
