from datetime import datetime, timezone
from unittest.mock import Mock, patch

from django.test import TestCase

from apps.analysis.possible_reset import MAX_QUOTED_CHARACTERS, deliver_possible_reset, quote_author
from apps.analysis.reassessment import SuspiciousIrrelevanceError
from apps.configuration.models import SystemConfiguration
from apps.sources.models import Source, SourcePost
from apps.telegram.formatting import format_delivery_message

DAY_23 = (
    "Day 23/ Much requested iCloud Main & Calendar plugins. Just kidding, today is a reset.\n"
    "Still much requested though!"
)


class PossibleResetTests(TestCase):
    def setUp(self):
        self.post = SourcePost.objects.create(
            source=Source.objects.get(username="thsottiaux"),
            external_id="2115273064481218829", text=DAY_23, normalized_text=DAY_23,
            source_url="https://x.com/thsottiaux/status/2115273064481218829",
            published_at=datetime(2026, 10, 28, 9, 40, tzinfo=timezone.utc), raw_data={},
        )

    @patch("apps.analysis.possible_reset.queue_analysis_deliveries")
    def test_group_post_matches_the_approved_layout(self, queue):
        queue.return_value = Mock(delivery_ids=(1,))
        result = deliver_possible_reset(
            source_post=self.post, configuration=SystemConfiguration.load(),
            exc=SuspiciousIrrelevanceError(detail="нет.", raw_response={"id": "audit"}),
        )
        self.assertEqual(result["queued_deliveries"], 1)
        self.assertEqual(
            format_delivery_message(self.post.analysis),
            "Codex: ВОЗМОЖНЫЙ СБРОС КВОТ\n\n"
            f"«{DAY_23}»\n\n"
            "Опубликовано: 28 октября 2026, 12:40 МСК\n"
            "Источник: https://x.com/thsottiaux/status/2115273064481218829",
        )

    def test_long_publication_is_shortened_to_fit_one_message(self):
        quoted = quote_author("a" * (MAX_QUOTED_CHARACTERS + 50))
        self.assertEqual(quoted, "«" + "a" * MAX_QUOTED_CHARACTERS + "…»")
