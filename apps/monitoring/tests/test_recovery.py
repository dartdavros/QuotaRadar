from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.utils import timezone

from apps.monitoring.recovery import recover_orphaned_work
from apps.sources.models import Source, SourcePost, SourcePostProcessingStatus
from apps.telegram.models import (
    Delivery,
    DeliveryStatus,
    DeliveryTarget,
    DeliveryTargetType,
)
from apps.telegram.tests.helpers import create_relevant_analysis


@override_settings(
    QUOTARADAR_ANALYSIS_STALE_SECONDS=600,
    QUOTARADAR_DELIVERY_STALE_SECONDS=600,
)
class RecoveryTests(TestCase):
    def test_requeues_only_stale_analysis_records(self) -> None:
        source = Source.objects.get(username="OpenAIDevs")
        stale = SourcePost.objects.create(
            source=source,
            external_id="7001",
            text="stale",
            normalized_text="stale",
            source_url="https://x.com/OpenAIDevs/status/7001",
            published_at=timezone.now(),
            raw_data={},
            processing_status=SourcePostProcessingStatus.QUEUED,
            processing_started_at=timezone.now() - timedelta(minutes=20),
        )
        recent = SourcePost.objects.create(
            source=source,
            external_id="7002",
            text="recent",
            normalized_text="recent",
            source_url="https://x.com/OpenAIDevs/status/7002",
            published_at=timezone.now(),
            raw_data={},
            processing_status=SourcePostProcessingStatus.QUEUED,
            processing_started_at=timezone.now(),
        )

        with (
            patch("apps.analysis.tasks.analyze_post.delay") as analyze_delay,
            patch("apps.telegram.tasks.deliver_analysis.delay"),
        ):
            result = recover_orphaned_work()

        self.assertEqual(result.analyses_queued, 1)
        analyze_delay.assert_called_once_with(stale.pk)
        recent.refresh_from_db()
        self.assertLess(
            timezone.now() - recent.processing_started_at,
            timedelta(minutes=1),
        )

    def test_failed_analysis_dispatch_remains_recoverable(self) -> None:
        source = Source.objects.get(username="OpenAIDevs")
        stale = SourcePost.objects.create(
            source=source,
            external_id="7040",
            text="stale dispatch",
            normalized_text="stale dispatch",
            source_url="https://x.com/OpenAIDevs/status/7040",
            published_at=timezone.now(),
            raw_data={},
            processing_status=SourcePostProcessingStatus.QUEUED,
            processing_started_at=timezone.now() - timedelta(minutes=20),
        )

        with (
            patch(
                "apps.analysis.tasks.analyze_post.delay",
                side_effect=RuntimeError("broker unavailable"),
            ),
            patch("apps.telegram.tasks.deliver_analysis.delay"),
        ):
            result = recover_orphaned_work()

        self.assertEqual(result.analysis_dispatch_errors, 1)
        stale.refresh_from_db()
        self.assertIsNone(stale.processing_started_at)
        self.assertEqual(
            stale.last_error,
            "Analysis recovery task could not be queued.",
        )

    def test_recreates_missing_delivery_fanout(self) -> None:
        analysis = create_relevant_analysis(external_id="7050")
        target = DeliveryTarget.objects.create(
            target_type=DeliveryTargetType.CHANNEL,
            telegram_chat_id="@quota_missing_fanout",
        )

        with (
            patch("apps.analysis.tasks.analyze_post.delay"),
            patch("apps.telegram.tasks.deliver_analysis.delay") as delivery_delay,
            self.captureOnCommitCallbacks(execute=True),
        ):
            result = recover_orphaned_work()

        self.assertEqual(result.fanouts_completed, 1)
        analysis.refresh_from_db()
        self.assertIsNotNone(analysis.delivery_fanout_completed_at)
        delivery = Delivery.objects.get(analysis=analysis, target=target)
        delivery_delay.assert_called_once_with(analysis.pk, target.pk)
        self.assertEqual(delivery.status, DeliveryStatus.PENDING)

    def test_requeues_stale_pending_delivery_but_not_permanent_failure(self) -> None:
        analysis = create_relevant_analysis(external_id="7101")
        target = DeliveryTarget.objects.create(
            target_type=DeliveryTargetType.CHANNEL,
            telegram_chat_id="@quota_recovery",
        )
        stale_pending = Delivery.objects.create(
            analysis=analysis,
            target=target,
            status=DeliveryStatus.PENDING,
        )
        Delivery.objects.filter(pk=stale_pending.pk).update(
            created_at=timezone.now() - timedelta(minutes=20)
        )
        scheduled_target = DeliveryTarget.objects.create(
            target_type=DeliveryTargetType.CHANNEL,
            telegram_chat_id="@quota_scheduled",
        )
        scheduled = Delivery.objects.create(
            analysis=analysis,
            target=scheduled_target,
            status=DeliveryStatus.PENDING,
            next_attempt_at=timezone.now() + timedelta(minutes=10),
        )
        Delivery.objects.filter(pk=scheduled.pk).update(
            created_at=timezone.now() - timedelta(minutes=20)
        )
        failed_target = DeliveryTarget.objects.create(
            target_type=DeliveryTargetType.CHANNEL,
            telegram_chat_id="@quota_failed",
        )
        Delivery.objects.create(
            analysis=analysis,
            target=failed_target,
            status=DeliveryStatus.FAILED,
        )

        with (
            patch("apps.analysis.tasks.analyze_post.delay"),
            patch("apps.telegram.tasks.deliver_analysis.delay") as delivery_delay,
        ):
            result = recover_orphaned_work()

        self.assertEqual(result.deliveries_queued, 1)
        delivery_delay.assert_called_once_with(analysis.pk, target.pk)
