from contextlib import contextmanager
from datetime import datetime, timezone
from unittest.mock import Mock, patch

from django.test import TestCase

from apps.configuration.models import SystemConfiguration
from apps.monitoring.services import PollResult, ResolutionResult
from apps.monitoring.tasks import healthcheck, poll_source, poll_sources
from apps.monitoring.x_api import XApiAuthenticationError, XApiRateLimitError
from apps.sources.models import Source, SourcePost, SourcePostProcessingStatus


@contextmanager
def acquired_lock(source_id: int):
    yield True


@contextmanager
def rejected_lock(source_id: int):
    yield False


class HealthcheckTaskTests(TestCase):
    def test_returns_worker_status(self) -> None:
        self.assertEqual(
            healthcheck.run(),
            {"status": "ok", "service": "worker"},
        )


class PollSourcesTaskTests(TestCase):
    def setUp(self) -> None:
        self.configuration = SystemConfiguration.load()

    def test_monitoring_disabled_does_not_call_x_or_enqueue(self) -> None:
        with (
            patch("apps.monitoring.tasks.XApiClient") as client_class,
            patch("apps.monitoring.tasks.poll_source.delay") as delay,
        ):
            result = poll_sources.run()

        self.assertEqual(result, {"status": "disabled", "queued": 0})
        client_class.assert_not_called()
        delay.assert_not_called()

    @patch("apps.monitoring.tasks.poll_source.delay")
    @patch("apps.monitoring.tasks.resolve_source_user_ids")
    @patch("apps.monitoring.tasks.XApiClient")
    def test_resolves_and_enqueues_each_active_source(
        self,
        client_class: Mock,
        resolve: Mock,
        delay: Mock,
    ) -> None:
        self.configuration.monitoring_enabled = True
        self.configuration.save()
        sources = list(Source.objects.filter(enabled=True).order_by("pk"))
        resolve.return_value = ResolutionResult(
            resolved_source_ids=tuple(source.pk for source in sources),
            unresolved_source_ids=(),
        )

        result = poll_sources.run()

        self.assertEqual(result["queued"], 2)
        self.assertEqual(delay.call_count, 2)
        client_class.assert_called_once_with()


class PollSourceTaskTests(TestCase):
    def setUp(self) -> None:
        self.configuration = SystemConfiguration.load()
        self.configuration.monitoring_enabled = True
        self.configuration.retry_count = 4
        self.configuration.save()
        self.source = Source.objects.get(username="OpenAIDevs")
        self.source.x_user_id = "1001"
        self.source.save()

    @patch("apps.monitoring.tasks.source_poll_lock", rejected_lock)
    def test_parallel_poll_is_skipped(self) -> None:
        result = poll_source.run(self.source.pk)

        self.assertEqual(result["status"], "locked")

    @patch("apps.monitoring.tasks.source_poll_lock", acquired_lock)
    @patch("apps.monitoring.tasks.ingest_source_posts")
    @patch("apps.monitoring.tasks.XApiClient")
    def test_success_returns_ingestion_counts(
        self,
        client_class: Mock,
        ingest: Mock,
    ) -> None:
        ingest.return_value = PollResult(
            source_id=self.source.pk,
            pages=2,
            created_posts=3,
            existing_posts=0,
            ignored_retweets=1,
            last_post_id="105",
        )

        result = poll_source.run(self.source.pk)

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["created_posts"], 3)
        client_class.assert_called_once_with()

    @patch("apps.monitoring.tasks.analyze_post.delay")
    @patch("apps.monitoring.tasks.source_poll_lock", acquired_lock)
    @patch("apps.monitoring.tasks.ingest_source_posts")
    @patch("apps.monitoring.tasks.XApiClient")
    def test_success_queues_received_backlog_for_analysis(
        self,
        client_class: Mock,
        ingest: Mock,
        analyze_delay: Mock,
    ) -> None:
        post = SourcePost.objects.create(
            source=self.source,
            external_id="9001",
            text="Quota update",
            normalized_text="Quota update",
            source_url="https://x.com/OpenAIDevs/status/9001",
            published_at=datetime(2026, 7, 20, 10, 0, tzinfo=timezone.utc),
            raw_data={},
        )
        ingest.return_value = PollResult(
            source_id=self.source.pk,
            pages=1,
            created_posts=0,
            existing_posts=1,
            ignored_retweets=0,
            last_post_id="9001",
        )

        result = poll_source.run(self.source.pk)

        self.assertEqual(result["queued_analyses"], 1)
        analyze_delay.assert_called_once_with(post.pk)
        post.refresh_from_db()
        self.assertEqual(post.processing_status, SourcePostProcessingStatus.QUEUED)

    @patch("apps.monitoring.tasks.source_poll_lock", acquired_lock)
    @patch("apps.monitoring.tasks.ingest_source_posts")
    @patch("apps.monitoring.tasks.XApiClient")
    def test_rate_limit_retries_at_reset_time(
        self,
        client_class: Mock,
        ingest: Mock,
    ) -> None:
        error = XApiRateLimitError(reset_at=200)
        error.retry_after_seconds = Mock(return_value=51)  # type: ignore[method-assign]
        ingest.side_effect = error

        with patch.object(
            poll_source,
            "retry",
            side_effect=RuntimeError("retry requested"),
        ) as retry:
            with self.assertRaisesRegex(RuntimeError, "retry requested"):
                poll_source.run(self.source.pk)

        retry.assert_called_once()
        self.assertEqual(retry.call_args.kwargs["countdown"], 51)
        self.assertEqual(retry.call_args.kwargs["max_retries"], 4)
        self.source.refresh_from_db()
        self.assertEqual(self.source.last_error, "X API rate limit exceeded.")

    @patch("apps.monitoring.tasks.source_poll_lock", acquired_lock)
    @patch("apps.monitoring.tasks.ingest_source_posts")
    @patch("apps.monitoring.tasks.XApiClient")
    def test_authentication_error_is_recorded_without_retry(
        self,
        client_class: Mock,
        ingest: Mock,
    ) -> None:
        ingest.side_effect = XApiAuthenticationError(
            "X API rejected the configured bearer token."
        )

        with patch.object(poll_source, "retry") as retry:
            result = poll_source.run(self.source.pk)

        self.assertEqual(result["status"], "error")
        retry.assert_not_called()
        self.source.refresh_from_db()
        self.assertEqual(
            self.source.last_error,
            "X API rejected the configured bearer token.",
        )
