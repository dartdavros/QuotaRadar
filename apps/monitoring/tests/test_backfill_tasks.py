from contextlib import contextmanager
from unittest.mock import Mock, patch

from django.test import TestCase

from apps.configuration.models import SystemConfiguration
from apps.monitoring.backfill import BackfillResult, BackfillUnavailableError
from apps.monitoring.backfill_tasks import backfill_source
from apps.monitoring.dispatch import AnalysisDispatchResult
from apps.monitoring.models import (
    MonitoringComponent,
    MonitoringEvent,
    MonitoringEventStatus,
)
from apps.monitoring.x_api import XApiRateLimitError
from apps.sources.models import Source


@contextmanager
def acquired_lock(source_id: int):
    yield True


@contextmanager
def rejected_lock(source_id: int):
    yield False


class BackfillSourceTaskTests(TestCase):
    def setUp(self) -> None:
        self.configuration = SystemConfiguration.load()
        self.configuration.retry_count = 4
        self.configuration.save(update_fields=("retry_count",))
        self.source = Source.objects.get(username="OpenAIDevs")
        self.source.x_user_id = "1001"
        self.source.last_post_id = "200"
        self.source.save(update_fields=("x_user_id", "last_post_id"))

    @patch("apps.monitoring.backfill_tasks.source_poll_lock", rejected_lock)
    def test_parallel_import_is_skipped(self) -> None:
        result = backfill_source.run(self.source.pk)

        self.assertEqual(result["status"], "locked")

    @patch("apps.monitoring.backfill_tasks.enqueue_posts_for_analysis")
    @patch("apps.monitoring.backfill_tasks.ingest_source_history")
    @patch("apps.monitoring.backfill_tasks.source_poll_lock", acquired_lock)
    @patch("apps.monitoring.backfill_tasks.XApiClient")
    def test_success_imports_and_queues_only_created_posts(
        self,
        client_class: Mock,
        ingest: Mock,
        enqueue: Mock,
    ) -> None:
        ingest.return_value = BackfillResult(
            source_id=self.source.pk,
            pages=2,
            created_posts=2,
            existing_posts=0,
            ignored_retweets=1,
            created_post_ids=(10, 11),
            history_cursor="200",
        )
        enqueue.return_value = AnalysisDispatchResult(
            requested=2,
            queued=2,
            skipped=0,
            dispatch_failed=0,
        )

        result = backfill_source.run(self.source.pk)

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["queued_analyses"], 2)
        ingest.assert_called_once_with(
            self.source,
            client_class.return_value.__enter__.return_value,
            self.configuration,
        )
        enqueue.assert_called_once()
        self.assertEqual(enqueue.call_args.kwargs["post_ids"], (10, 11))
        self.source.refresh_from_db()
        self.assertEqual(self.source.last_post_id, "200")
        event = MonitoringEvent.objects.get(
            component=MonitoringComponent.X,
            status=MonitoringEventStatus.SUCCESS,
            source=self.source,
        )
        self.assertIn("Исторический импорт завершён", event.message)

    @patch("apps.monitoring.backfill_tasks.ingest_source_history")
    @patch("apps.monitoring.backfill_tasks.source_poll_lock", acquired_lock)
    @patch("apps.monitoring.backfill_tasks.XApiClient")
    def test_unavailable_import_is_recorded_without_retry(
        self,
        client_class: Mock,
        ingest: Mock,
    ) -> None:
        ingest.side_effect = BackfillUnavailableError("no cursor")

        with patch.object(backfill_source, "retry") as retry:
            result = backfill_source.run(self.source.pk)

        self.assertEqual(result["status"], "unavailable")
        retry.assert_not_called()

    @patch("apps.monitoring.backfill_tasks.ingest_source_history")
    @patch("apps.monitoring.backfill_tasks.source_poll_lock", acquired_lock)
    @patch("apps.monitoring.backfill_tasks.XApiClient")
    def test_rate_limit_uses_configured_retry_policy(
        self,
        client_class: Mock,
        ingest: Mock,
    ) -> None:
        error = XApiRateLimitError(reset_at=200)
        error.retry_after_seconds = Mock(return_value=51)  # type: ignore[method-assign]
        ingest.side_effect = error

        with patch.object(
            backfill_source,
            "retry",
            side_effect=RuntimeError("retry requested"),
        ) as retry:
            with self.assertRaisesRegex(RuntimeError, "retry requested"):
                backfill_source.run(self.source.pk)

        retry.assert_called_once()
        self.assertEqual(retry.call_args.kwargs["countdown"], 51)
        self.assertEqual(retry.call_args.kwargs["max_retries"], 4)
