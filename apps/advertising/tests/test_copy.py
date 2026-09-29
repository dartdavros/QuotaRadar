from django.core.exceptions import ValidationError
from django.test import SimpleTestCase

from apps.advertising.formatting import AD_LIMIT, PREFIX, advertising_text, utf16_length, validate_copy
from apps.advertising.models import Campaign
from apps.telegram.models import DeliveryTarget, DeliveryTargetType
from .base import AdvertisingTestCase


class CopyLengthTests(SimpleTestCase):
    def test_exact_limit_counts_prefix_space_and_label(self):
        length = AD_LIMIT - utf16_length(PREFIX + " Ссылка")
        message = "я" * length
        validate_copy(message, "Ссылка", "https://example.com")
        self.assertEqual(utf16_length(advertising_text(message, "Ссылка")), 200)
        with self.assertRaises(ValidationError):
            validate_copy(message + "я", "Ссылка", "https://example.com")

    def test_emoji_and_combining_sequences_use_utf16_units(self):
        self.assertEqual(utf16_length("😀"), 2)
        self.assertEqual(utf16_length("👩‍💻"), 5)
        self.assertEqual(utf16_length("е\u0301"), 2)

    def test_url_is_separate_and_does_not_use_visible_budget(self):
        validate_copy("Курс", "Программа", "https://example.com/" + "x" * 1000)
        for message, label, url in [("Курс\nAI", "Программа", "https://example.com"),
                                    ("https://example.com", "Программа", "https://example.com"),
                                    ("Курс", "Программа", "javascript:alert(1)")]:
            with self.subTest(message=message, url=url), self.assertRaises(ValidationError):
                validate_copy(message, label, url)


class CampaignPolicyTests(AdvertisingTestCase):
    def test_only_quota_channels_are_eligible(self):
        for kind, chat_id, feed in [(DeliveryTargetType.PRIVATE_CHAT, "12345", "quota"),
                                    (DeliveryTargetType.CHANNEL, "@news_ads", "news")]:
            target = DeliveryTarget.objects.create(target_type=kind, telegram_chat_id=chat_id, feed=feed)
            with self.subTest(feed=feed), self.assertRaises(ValidationError):
                Campaign.objects.create(target=target, message="Курс", link_label="Программа",
                                        url="https://example.com", total_posts=1)

    def test_only_one_active_campaign_per_channel(self):
        with self.assertRaises(ValidationError):
            Campaign.objects.create(target=self.target, message="Другая кампания", link_label="Сайт",
                                    url="https://example.com", total_posts=1, enabled=True)

    def test_zero_posts_rejected(self):
        self.campaign.total_posts = 0
        with self.assertRaises(ValidationError):
            self.campaign.save()
