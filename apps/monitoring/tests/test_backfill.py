from datetime import datetime, timezone
from unittest.mock import Mock

from django.test import TestCase

from apps.configuration.models import SystemConfiguration
from apps.monitoring.backfill import (
    BackfillUnavailableError,
    ingest_source_history,
)
from apps.monitoring.tests.test_services import page_from_fixture
from apps.sources.models import Source, SourcePost, SourcePostProcessingStatus


class SourceBackfillTests(TestCase):
    def setUp(self) -> None:
        self.source = Source.objects.get(username="OpenAIDevs")
        self.source.x_user_id = "1001"
        self.source.last_post_id = "200"
        self.source.save(update_fields=("x_user_id", "last_post_id"))
        self.configuration = SystemConfiguration.load()
        self.pages = [
            page_from_fixture("timeline_page_1.json"),
            page_from_fixture("timeline_page_2.json"),
        ]
        SourcePost.objects.create(
            source=self.source,
            external_id="200",
            text="Current oldest post",
            normalized_text="Current oldest post",
            source_url="https://x.com/OpenAIDevs/status/200",
            published_at=datetime(2026, 7, 21, 10, 0, tzinfo=timezone.utc),
            raw_data={},
            processing_status=SourcePostProcessingStatus.ANALYZED_IRRELEVANT,
        )

    def test_imports_older_posts_without_changing_regular_poll_cursor(self) -> None:
        client = Mock()
        client.iter_user_posts.return_value = iter(self.pages)

        result = ingest_source_history(self.source, client, self.configuration)

        client.iter_user_posts.assert_called_once_with(
            "1001",
            since_id=None,
            until_id="199",
            max_results=100,
            max_pages=None,
            max_total_results=100,
        )
        self.source.refresh_from_db()
        self.assertEqual(self.source.last_post_id, "200")
        self.assertEqual(result.created_posts, 3)
        self.assertEqual(result.ignored_retweets, 1)
        self.assertEqual(len(result.created_post_ids), 3)
        self.assertEqual(
            list(
                SourcePost.objects.filter(pk__in=result.created_post_ids)
                .order_by("published_at", "pk")
                .values_list("external_id", flat=True)
            ),
            ["102", "103", "104"],
        )

    def test_limit_comes_from_system_configuration(self) -> None:
        self.configuration.historical_backfill_post_limit = 250
        self.configuration.save(update_fields=("historical_backfill_post_limit",))
        client = Mock()
        client.iter_user_posts.return_value = iter([])

        ingest_source_history(self.source, client, self.configuration)

        client.iter_user_posts.assert_called_once_with(
            "1001",
            since_id=None,
            until_id="199",
            max_results=100,
            max_pages=None,
            max_total_results=250,
        )

    def test_requires_existing_post_or_saved_cursor(self) -> None:
        SourcePost.objects.all().delete()
        self.source.last_post_id = ""
        self.source.save(update_fields=("last_post_id",))

        with self.assertRaises(BackfillUnavailableError):
            ingest_source_history(self.source, Mock(), self.configuration)
