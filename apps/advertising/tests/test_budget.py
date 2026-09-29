from apps.advertising.budget import quota_message_limit
from apps.advertising.formatting import utf16_length
from apps.analysis.quality import AnalysisQualityError, validate_payload_for_post
from apps.analysis.schemas import AnalysisPayload
from apps.telegram.formatting import format_message_values
from .base import AdvertisingTestCase


class AnalysisBudgetTests(AdvertisingTestCase):
    def test_active_campaign_reserves_full_block_and_separator(self):
        self.assertEqual(quota_message_limit(), 3894)
        self.campaign.enabled = False
        self.campaign.save()
        self.assertEqual(quota_message_limit(), 4096)

    def test_quality_limit_includes_publication_date_and_source(self):
        post = self.delivery.analysis.source_post
        title = "Лимиты Codex увеличены"
        overhead = utf16_length(format_message_values(title, "я", post)) - 1
        values = dict(is_relevant=True, event_type="quota_increase", provider="openai", product="codex", title_ru=title)
        valid = AnalysisPayload(**values, message_ru="я" * (3894 - overhead))
        validate_payload_for_post(payload=valid, source_post=post)
        invalid = valid.model_copy(update={"message_ru": valid.message_ru + "я"})
        with self.assertRaises(AnalysisQualityError):
            validate_payload_for_post(payload=invalid, source_post=post)
