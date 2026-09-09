"""Historical policies use isolated real PostgreSQL records, never live API requests."""
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch
from django.test import TestCase, override_settings
from django.utils import timezone
from apps.sources.models import Source, SourcePost
from apps.telegram.models import DeliveryTarget
from apps.news.budget import reserve, settle, BudgetExhausted
from apps.news.errors import NewsPolicyError
from apps.news.fill_collection import advance
from apps.news.fill_delivery import fill_ready, frozen
from apps.news.preparation import prepare
from apps.news.schemas import HistoricalVerificationPayload, WritingPayload
from apps.news.initial_fill import (FILL_LIMIT, start_fill, register_archive, rank,
                                    remaining, select_initial)
from apps.news.models import (InitialFill, NewsAssessment, NewsConfiguration, NewsDailyQuota,
                             NewsDelivery, NewsEvent, NewsEventEvidence, NewsPublication, XBudgetPeriod)
from apps.news.payload import publication_expired, publication_allowed
from apps.news.scheduling import select_publication, local_day, reserve_day


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

    def evidence(self, number, days=2, score=90, kind="tool_release", product="Codex"):
        date = self.now-timedelta(days=days)
        post = SourcePost.objects.create(source=self.source, external_id=str(number),
            text="Codex adds review.", normalized_text="Codex adds review.",
            source_url=f"https://x.com/OpenAIDevs/status/{number}", published_at=date, raw_data={})
        NewsAssessment.objects.create(post=post, status="done")
        event = NewsEvent.objects.create(fingerprint=str(number), product=product, version=str(number),
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

    def test_first_run_is_unique_per_target_and_uses_four_day_archive(self):
        self.evidence(1)
        self.evidence(2, days=6)
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

    def test_fill_reads_accounts_without_the_topic_filter(self):
        run = start_fill()
        self.assertTrue(run.sources.exists())
        self.assertFalse(run.sources.exclude(query_terms="").exists())

    def test_history_is_released_in_x_order_over_the_whole_window(self):
        # Five products spread over the four-day window, assessed in a deliberately shuffled order.
        for n, (product, days) in enumerate((("Gemini", 1.4), ("Codex", 3.8), ("Cursor", 0.6), ("Astra", 2.2), ("Sora", 3.0))):
            self.evidence(n, product=product, days=days)
        # Claude Tag was first posted 3.9 days ago, but that post reached the event only after a later one.
        tag = self.evidence(9, product="Claude Tag", days=0.5)
        early = SourcePost.objects.create(source=self.source, external_id="early-tag", text="Claude Tag.",
            normalized_text="Claude Tag.", source_url="https://x.com/OpenAIDevs/status/early-tag",
            published_at=self.now-timedelta(days=3.9), raw_data={})
        NewsAssessment.objects.create(post=early, status="done")
        NewsEventEvidence.objects.create(event=tag, post=early, facts=[])
        run = start_fill()
        run.status = "assessing"
        run.save()
        select_initial(run.pk)
        run.publications.update(status="ready")
        run.refresh_from_db()
        self.assertTrue(frozen(run))
        sent, clock = [], self.now
        while run.publications.exclude(status="sent").exists():
            ready = [p for p in run.publications.exclude(status="sent").select_related("event") if fill_ready(p, clock)]
            self.assertEqual(len(ready), 1, "exactly one post may leave at a time")
            publication = ready[0]
            run.publications.filter(pk=publication.pk).update(status="sent")
            NewsDelivery.objects.create(publication=publication, sent_at=clock)
            happened = publication.event.evidence.order_by("post__published_at").first().post.published_at
            sent.append((publication.event.product, happened))
            clock += timedelta(seconds=30)
        print("\n  delivery order:", " -> ".join(f"{p} ({(self.now-t).days}d {(self.now-t).seconds//3600}h ago)" for p, t in sent))
        self.assertEqual([p for p, _ in sent], ["Claude Tag", "Codex", "Sora", "Astra", "Gemini", "Cursor"])
        self.assertEqual([t for _, t in sent], sorted(t for _, t in sent))

    def test_history_keeps_a_supported_text_even_if_its_offer_expired(self):
        event = self.evidence(1, product="Astra")
        run = start_fill()
        publication = NewsPublication.objects.create(event=event, target=self.target, initial_fill=run, attempts=4)
        writing = WritingPayload(title="Astra развёрнута для пользователей Plus и Pro",
                                 text="Astra доступна в Codex и ChatGPT Work.\n\nСброс лимитов прошёл раньше срока.")
        verdict = HistoricalVerificationPayload(supported=True, reason="Подтверждено", still_relevant=False)
        with patch("apps.news.preparation.ask", side_effect=[(writing, "m", {}), (verdict, "m", {})]):
            prepare(publication.pk, self.config)
        publication.refresh_from_db()
        # Attempt five of six: history outlives a flaky provider and is not rejected for being old.
        self.assertEqual((publication.status, publication.attempts), ("ready", 5))
        self.assertNotIn("2026", publication.rendered)

    def test_three_products_no_longer_cancel_the_paid_history_read(self):
        for n, product in enumerate(("Codex", "Claude Code", "Cursor")):
            self.evidence(n, product=product)
        run = start_fill()
        advance(run.pk, self.config)
        run.refresh_from_db()
        # Seeding a channel needs the whole window, not the few items the archive happens to hold.
        self.assertEqual(run.status, "collecting")
        self.assertEqual(run.committed, 0)
        self.assertIsNone(select_publication())

    def test_archive_already_filling_the_run_skips_paid_collection(self):
        for n in range(FILL_LIMIT):
            self.evidence(n, product=f"Product {n}")
        run = start_fill()
        advance(run.pk, self.config)
        run.refresh_from_db()
        self.assertEqual(run.status, "assessing")
        self.assertEqual(run.committed, 0)
        self.assertFalse(XBudgetPeriod.objects.exists())
        select_initial(run.pk)
        self.assertEqual(run.publications.count(), FILL_LIMIT)

    def test_archive_repeating_one_product_still_reads_paid_history(self):
        for n in range(4):
            self.evidence(n)
        run = start_fill()
        advance(run.pk, self.config)
        run.refresh_from_db()
        # Four takes on the same product are one news item, not enough to cancel the history read.
        self.assertEqual(run.status, "collecting")
        self.assertEqual(run.committed, 0)

    def test_rank_keeps_one_best_event_per_product_oldest_first(self):
        self.evidence(1, score=99, days=1)
        self.evidence(2, score=95, days=1)
        self.evidence(3, score=80, product="Cursor", days=3)
        picked = rank(start_fill(), FILL_LIMIT)
        self.assertEqual([event.product for event in picked], ["Cursor", "Codex"])
        self.assertEqual([event.score for event in picked], [80, 99])

    def test_history_is_sent_oldest_first_with_a_pause_between_posts(self):
        for n, (product, days) in enumerate((("Cursor", 3), ("Codex", 1))):
            self.evidence(n, product=product, days=days)
        run = start_fill()
        run.status = "assessing"
        run.save()
        select_initial(run.pk)
        run.publications.update(status="ready")
        run.refresh_from_db()
        self.assertTrue(frozen(run))
        first, second = run.publications.order_by("event__first_seen_at")
        self.assertEqual([first.event.product, second.event.product], ["Cursor", "Codex"])
        self.assertTrue(fill_ready(first, self.now))
        self.assertFalse(fill_ready(second, self.now))
        run.publications.filter(pk=first.pk).update(status="sent")
        NewsDelivery.objects.create(publication=first, sent_at=self.now)
        self.assertFalse(fill_ready(second, self.now+timedelta(seconds=29)))
        self.assertTrue(fill_ready(second, self.now+timedelta(seconds=30)))

    def test_nothing_is_sent_while_another_event_can_still_join_the_run(self):
        for n, product in enumerate(("Codex", "Cursor")):
            self.evidence(n, product=product, days=2)
        run = start_fill()
        run.status = "assessing"
        run.save()
        select_initial(run.pk)
        run.publications.update(status="ready")
        run.refresh_from_db()
        self.assertTrue(frozen(run))
        # A later wave appears; delivery waits for it instead of racing ahead of older news.
        self.evidence(9, product="Gemini", days=3)
        register_archive(run)
        self.assertFalse(frozen(run))
        self.assertFalse(fill_ready(run.publications.order_by("pk").first(), self.now))

    def test_a_later_wave_still_publishes_before_the_newer_posts_it_predates(self):
        self.evidence(1, product="Codex", days=1)
        run = start_fill()
        run.status = "assessing"
        run.save()
        select_initial(run.pk)
        self.evidence(2, product="Cursor", days=3)
        register_archive(run)
        run.publications.update(status="ready")
        run.refresh_from_db()
        advance(run.pk, self.config)
        run.refresh_from_db()
        self.assertEqual(run.status, "assessing")
        select_initial(run.pk)
        run.publications.update(status="ready")
        run.refresh_from_db()
        self.assertTrue(frozen(run))
        oldest = run.publications.order_by("event__first_seen_at").first()
        newest = run.publications.order_by("-event__first_seen_at").first()
        self.assertEqual(oldest.event.product, "Cursor")
        self.assertTrue(fill_ready(oldest, self.now))
        self.assertFalse(fill_ready(newest, self.now))

    def test_a_product_already_published_never_returns_in_a_later_wave(self):
        self.evidence(1, product="Astra", score=90, days=1)
        self.evidence(2, product="Astra", score=85, days=3)
        run = start_fill()
        run.status = "assessing"
        run.save()
        select_initial(run.pk)
        self.assertEqual(run.publications.count(), 1)
        self.assertFalse(remaining(run))
        run.status = "assessing"
        run.save()
        select_initial(run.pk)
        self.assertEqual(run.publications.count(), 1)

    def test_selection_excludes_incidents_and_publishes_history_in_order(self):
        for n, (score, product, days) in enumerate(
                ((71, "Codex", 1), (80, "Cursor", 2), (95, "Claude Code", 3), (99, "Gemini", 3.5))):
            self.evidence(n, score=score, product=product, days=days)
        self.evidence(8, kind="incident", score=100, product="Sora")
        run = start_fill()
        run.status = "assessing"
        run.save()
        select_initial(run.pk)
        ordered = list(run.publications.order_by("pk").values_list("event__product", flat=True))
        self.assertEqual(ordered, ["Gemini", "Claude Code", "Cursor", "Codex"])
        self.assertFalse(run.publications.filter(event__event_type="incident").exists())
        self.assertFalse(run.publications.filter(urgent=True).exists())
        pub = run.publications.order_by("pk").first()
        self.assertLess(pub.event.expires_at, self.now)
        self.assertFalse(publication_expired(pub, self.now))
        self.assertTrue(publication_expired(pub, run.expires_at))
        with override_settings(QUOTARADAR_NEWS_INITIAL_FILL_ALLOWED=False):
            self.assertFalse(publication_allowed(pub, self.config))

    def test_daily_limit_neither_caps_nor_is_consumed_by_the_fill(self):
        self.config.daily_limit = 1
        self.config.save()
        today = local_day(self.config, self.now).date()
        for n, product in enumerate(("Codex", "Cursor", "Gemini")):
            self.evidence(n, product=product)
        for n in (10, 11):
            event = self.evidence(n, days=0)
            NewsPublication.objects.create(event=event, target=self.target, status="sent", slot_date=today)
        run = start_fill()
        run.status = "assessing"
        run.save()
        select_initial(run.pk)
        select_initial(run.pk)
        # Already published days and a stricter daily limit never shrink the one-time fill.
        self.assertEqual(run.publications.count(), 3)
        self.assertFalse(run.publications.exclude(slot_date=None).exists())
        self.assertFalse(NewsDailyQuota.objects.filter(target=self.target, date=today).exists())

    def test_fill_publications_leave_the_regular_daily_slot_free(self):
        self.config.daily_limit = 1
        self.config.save()
        for n, product in enumerate(("Codex", "Cursor", "Gemini")):
            self.evidence(n, product=product)
        run = start_fill()
        run.status = "assessing"
        run.save()
        select_initial(run.pk)
        self.assertEqual(run.publications.count(), 3)
        regular = NewsPublication(event=self.evidence(20, days=0), target=self.target)
        self.assertTrue(reserve_day(regular, self.config, self.now))
        self.assertEqual(regular.slot_date, local_day(self.config, self.now).date())

    @patch("apps.news.fill_collection.FILL_LIMIT", 3)
    @patch("apps.news.fill_delivery.FILL_LIMIT", 3)
    @patch("apps.news.initial_fill.FILL_LIMIT", 3)
    def test_rejected_publication_frees_its_slot_for_the_next_event(self):
        for n, product in enumerate(("Codex", "Claude Code", "Cursor", "Gemini")):
            self.evidence(n, product=product, score=90-n)
        run = start_fill()
        run.status = "assessing"
        run.save()
        select_initial(run.pk)
        self.assertEqual(run.publications.count(), 3)
        run.publications.update(status="sent")
        run.publications.filter(event__product="Codex").update(status="blocked")
        run.status = "publishing"
        run.save()
        advance(run.pk, self.config)
        run.refresh_from_db()
        self.assertEqual(run.status, "assessing")
        select_initial(run.pk)
        self.assertEqual(run.publications.exclude(status="blocked").count(), 3)
        self.assertTrue(run.publications.filter(event__product="Gemini").exists())
        run.publications.exclude(status="blocked").update(status="sent")
        advance(run.pk, self.config)
        run.refresh_from_db()
        self.assertEqual(run.status, "completed")

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
