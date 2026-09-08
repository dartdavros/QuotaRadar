"""Historical policies use isolated real PostgreSQL records, never live API requests."""
from datetime import timedelta
from decimal import Decimal
from django.test import TestCase, override_settings
from django.utils import timezone
from apps.sources.models import Source, SourcePost
from apps.telegram.models import DeliveryTarget
from apps.news.budget import reserve, settle, BudgetExhausted
from apps.news.errors import NewsPolicyError
from apps.news.fill_collection import advance
from apps.news.initial_fill import start_fill, register_archive, select_initial
from apps.news.models import (InitialFill, NewsAssessment, NewsConfiguration, NewsEvent,
                             NewsEventEvidence, NewsPublication, XBudgetPeriod)
from apps.news.payload import publication_expired, publication_allowed
from apps.news.scheduling import select_publication, local_day


@override_settings(QUOTARADAR_NEWS_INITIAL_FILL_ALLOWED=True)
class InitialFillTests(TestCase):
    def setUp(self):
        self.now = timezone.now()
        self.source = Source.objects.get(username="OpenAIDevs")
        self.target = DeliveryTarget.objects.create(target_type="channel", feed="news", telegram_chat_id="-100909")
        self.config = NewsConfiguration.load()
        self.config.target = self.target
        self.config.collection_enabled = self.config.analysis_enabled = self.config.publishing_enabled = True
        self.config.save()

    def evidence(self, number, days=2, score=90, kind="tool_release"):
        date = self.now-timedelta(days=days)
        post = SourcePost.objects.create(source=self.source, external_id=str(number),
            text="Codex adds review.", normalized_text="Codex adds review.",
            source_url=f"https://x.com/OpenAIDevs/status/{number}", published_at=date, raw_data={})
        NewsAssessment.objects.create(post=post, status="done")
        event = NewsEvent.objects.create(fingerprint=str(number), product="Codex", version=str(number),
            event_type=kind, score=score, urgent=True, facts=[], first_seen_at=date, last_seen_at=date,
            expires_at=date+timedelta(hours=36))
        NewsEventEvidence.objects.create(event=event, post=post, facts=[])
        return event

    @override_settings(QUOTARADAR_NEWS_INITIAL_FILL_ALLOWED=False)
    def test_local_start_is_blocked_before_any_write(self):
        with self.assertRaises(NewsPolicyError):
            start_fill()
        self.assertFalse(InitialFill.objects.exists())
        self.assertFalse(XBudgetPeriod.objects.exists())

    def test_first_run_is_unique_per_target_and_uses_three_day_archive(self):
        self.evidence(1)
        self.evidence(2, days=4)
        run = start_fill()
        self.assertEqual(run.assessments.count(), 1)
        self.assertEqual(run.committed, 0)
        self.assertEqual(run.status, "archive")
        with self.assertRaises(NewsPolicyError):
            start_fill()
        run.status = "completed"
        run.save()
        with self.assertRaises(NewsPolicyError):
            start_fill()

    def test_archive_with_three_candidates_skips_paid_collection(self):
        for n in range(3):
            self.evidence(n)
        run = start_fill()
        advance(run.pk, self.config)
        run.refresh_from_db()
        self.assertEqual(run.status, "assessing")
        self.assertEqual(run.committed, 0)
        self.assertFalse(XBudgetPeriod.objects.exists())
        select_initial(run.pk)
        select_initial(run.pk)
        self.assertEqual(run.publications.count(), 3)
        self.assertIsNone(select_publication())

    def test_initial_selection_ranks_events_excludes_incidents_and_caps_total(self):
        for n, score in enumerate((71, 80, 95, 99)):
            self.evidence(n, score=score)
        self.evidence(8, kind="incident", score=100)
        run = start_fill()
        run.status = "assessing"
        run.save()
        select_initial(run.pk)
        scores = list(run.publications.order_by("-event__score").values_list("event__score", flat=True))
        self.assertEqual(scores, [99, 95, 80])
        self.assertFalse(run.publications.filter(urgent=True).exists())
        pub = run.publications.first()
        self.assertLess(pub.event.expires_at, self.now)
        self.assertFalse(publication_expired(pub, self.now))
        self.assertTrue(publication_expired(pub, run.expires_at))
        with override_settings(QUOTARADAR_NEWS_INITIAL_FILL_ALLOWED=False):
            self.assertFalse(publication_allowed(pub, self.config))

    def test_existing_daily_posts_leave_only_one_fill_slot(self):
        for n in range(3):
            self.evidence(n)
        for n in (10, 11):
            event = self.evidence(n, days=0)
            NewsPublication.objects.create(event=event, target=self.target, status="sent", slot_date=local_day(self.config, self.now).date())
        run = start_fill()
        run.status = "assessing"
        run.save()
        select_initial(run.pk)
        select_initial(run.pk)
        self.assertEqual(run.publications.count(), 1)

    def test_two_dollar_cap_includes_unknown_and_settled_requests(self):
        run = start_fill()
        run.status = "collecting"
        run.save()
        first = reserve(self.source, self.config, maximum=Decimal(".050"), priority=True, initial_fill_id=run.pk)
        settle(first.pk, resources=2)
        reserve(self.source, self.config, maximum=Decimal("1.990"), priority=True, initial_fill_id=run.pk)
        with self.assertRaises(BudgetExhausted):
            reserve(self.source, self.config, maximum=Decimal(".050"), priority=True, initial_fill_id=run.pk)
        run.refresh_from_db()
        self.assertEqual(run.committed, Decimal("2"))
        self.assertEqual(XBudgetPeriod.objects.get().committed, Decimal("2"))

    def test_weekly_budget_is_not_bypassed_by_initial_fill(self):
        reserve(self.source, self.config, maximum=Decimal("2.970"), priority=True)
        run = start_fill()
        run.status = "collecting"
        run.save()
        with self.assertRaises(BudgetExhausted):
            reserve(self.source, self.config, maximum=Decimal(".050"), priority=True, initial_fill_id=run.pk)
        run.refresh_from_db()
        self.assertEqual(run.committed, 0)
        self.assertEqual(XBudgetPeriod.objects.get().committed, Decimal("2.970"))

    def test_normal_selection_cannot_publish_historical_urgent_during_fill(self):
        self.evidence(1, days=1)
        start_fill()
        self.assertIsNone(select_publication())
