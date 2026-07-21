from datetime import datetime, timezone
from unittest.mock import patch

from django.test import TestCase

from apps.monitoring.dispatch import enqueue_posts_for_analysis
from apps.sources.models import Source, SourcePost, SourcePostProcessingStatus


class AnalysisDispatchTests(TestCase):
    def setUp(self) -> None:
        self.source = Source.objects.get(username="OpenAIDevs")
        self.post = SourcePost.objects.create(
            source=self.source,
            external_id="9001",
            text="Post",
            normalized_text="Post",
            source_url="https://x.com/OpenAIDevs/status/9001",
            published_at=datetime(2026, 7, 21, 12, 0, tzinfo=timezone.utc),
            raw_data={},
            processing_status=SourcePostProcessingStatus.FAILED,
            last_error="Previous analysis error.",
        )

    @patch("apps.monitoring.dispatch.analyze_post.delay")
    def test_failed_post_is_claimed_and_queued(self, delay) -> None:
        result = enqueue_posts_for_analysis(
            post_ids=[self.post.pk],
            eligible_statuses=(SourcePostProcessingStatus.FAILED,),
        )

        self.assertEqual(result.requested, 1)
        self.assertEqual(result.queued, 1)
        self.assertEqual(result.skipped, 0)
        self.assertEqual(result.dispatch_failed, 0)
        delay.assert_called_once_with(self.post.pk)
        self.post.refresh_from_db()
        self.assertEqual(
            self.post.processing_status,
            SourcePostProcessingStatus.QUEUED,
        )
        self.assertIsNotNone(self.post.processing_started_at)
        self.assertEqual(self.post.last_error, "")

    @patch("apps.monitoring.dispatch.analyze_post.delay")
    def test_dispatch_failure_restores_previous_failed_state(self, delay) -> None:
        delay.side_effect = RuntimeError("broker unavailable")

        result = enqueue_posts_for_analysis(
            post_ids=[self.post.pk],
            eligible_statuses=(SourcePostProcessingStatus.FAILED,),
        )

        self.assertEqual(result.queued, 0)
        self.assertEqual(result.dispatch_failed, 1)
        self.post.refresh_from_db()
        self.assertEqual(
            self.post.processing_status,
            SourcePostProcessingStatus.FAILED,
        )
        self.assertIsNone(self.post.processing_started_at)
        self.assertEqual(self.post.last_error, "Previous analysis error.")

    @patch("apps.monitoring.dispatch.analyze_post.delay")
    def test_ineligible_status_is_skipped(self, delay) -> None:
        self.post.processing_status = SourcePostProcessingStatus.ANALYZED_IRRELEVANT
        self.post.save(update_fields=("processing_status",))

        result = enqueue_posts_for_analysis(
            post_ids=[self.post.pk],
            eligible_statuses=(SourcePostProcessingStatus.FAILED,),
        )

        self.assertEqual(result.queued, 0)
        self.assertEqual(result.skipped, 1)
        delay.assert_not_called()
