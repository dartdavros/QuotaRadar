"""Deterministic policies and real database invariants; no external API calls."""
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from django.core.exceptions import ValidationError
from django.db import transaction
from django.test import TestCase, SimpleTestCase
from django.utils import timezone
from apps.sources.models import Feed, Source, SourcePost, SourceSubscription
from apps.sources.routing import accepts_quota
from apps.telegram.models import DeliveryTarget
from apps.news.budget import reserve, settle, BudgetExhausted
from apps.news.collection import register_posts
from apps.news.editorial import save_event
from apps.news.media import attachment_plan, validate_url
from apps.news.models import NewsAssessment, NewsConfiguration, NewsDelivery, NewsEvent, NewsPublication, XBudgetPeriod
from apps.news.quality import editorial, render, validate_assessment
from apps.news.schemas import AssessmentPayload, Fact, WritingPayload
from apps.news.scheduling import reserve_day, select_publication
from apps.news.sending import resolve
from apps.news.transport import parse_receipt, DeliveryUncertain, DeliveryRateLimited, DeliveryRejected
from apps.news.x_client import build_query

class NewsPolicyTests(TestCase):
    def setUp(self):
        self.config = NewsConfiguration.load()
        self.source = Source.objects.get(username="OpenAIDevs")
        self.now = timezone.now()
        self.target = DeliveryTarget.objects.create(
            target_type="channel", feed=Feed.NEWS, telegram_chat_id="-100778899")
        self.config.target = self.target
        self.config.activated_at = self.now-timedelta(hours=1)
        self.config.publishing_enabled = True
        self.config.save()

    def post(self, number="991", **changes):
        data = dict(source=self.source, external_id=number, text="Codex adds code review.",
                    normalized_text="Codex adds code review.", source_url=f"https://x.com/OpenAIDevs/status/{number}",
                    published_at=self.now, raw_data={})
        data.update(changes)
        return SourcePost.objects.create(**data)

    def event(self, number, urgent=True, score=90):
        return NewsEvent.objects.create(fingerprint=str(number), product="Codex", version=str(number),
            event_type="tool_release", score=score, urgent=urgent, facts=[{"text": "Факт"}],
            first_seen_at=self.now, last_seen_at=self.now, expires_at=self.now+timedelta(hours=3))

    def test_defaults_are_opt_in_and_news_only_accounts_do_not_reach_quota(self):
        self.assertFalse(self.config.collection_enabled)
        self.assertFalse(self.config.analysis_enabled)
        self.assertEqual(SourceSubscription.objects.filter(feed="news").count(), 8)
        self.assertFalse(accepts_quota(Source.objects.get(username="cursor_ai").pk))
        self.assertTrue(accepts_quota(self.source.pk))

    def test_shared_archive_registration_does_not_touch_quota_status(self):
        post = self.post(processing_status="analyzed_irrelevant")
        register_posts(self.config)
        register_posts(self.config)
        self.assertEqual(NewsAssessment.objects.filter(post=post).count(), 1)
        post.refresh_from_db()
        self.assertEqual(post.processing_status, "analyzed_irrelevant")

    def test_activation_excludes_historical_posts(self):
        self.post(published_at=self.now-timedelta(days=1))
        self.assertEqual(register_posts(self.config), 0)

    def test_budget_reservation_settlement_and_unknown_response(self):
        usage = reserve(self.source, self.config, maximum=Decimal(".050"), priority=True)
        settle(usage.pk, resources=2)
        settle(usage.pk, resources=2)
        self.assertEqual(XBudgetPeriod.objects.get().committed, Decimal(".010"))
        second = reserve(self.source, self.config, maximum=Decimal(".050"), priority=True)
        settle(second.pk)
        settle(second.pk, resources=0)
        self.assertEqual(XBudgetPeriod.objects.get().committed, Decimal(".060"))

    def test_priority_reserve_and_strict_weekly_cap(self):
        reserve(self.source, self.config, maximum=Decimal("2.400"), priority=False)
        with self.assertRaises(BudgetExhausted):
            reserve(self.source, self.config, maximum=Decimal(".050"), priority=False)
        reserve(self.source, self.config, maximum=Decimal(".600"), priority=True)
        with self.assertRaises(BudgetExhausted):
            reserve(self.source, self.config, maximum=Decimal(".050"), priority=True)
        self.assertEqual(XBudgetPeriod.objects.get().committed, Decimal("3.000"))

    def test_urgent_selection_still_stops_at_three(self):
        for n in range(4):
            self.event(n)
        self.assertIsNotNone(select_publication())
        self.assertIsNotNone(select_publication())
        self.assertIsNotNone(select_publication())
        self.assertIsNone(select_publication())
        self.assertEqual(NewsPublication.objects.count(), 3)

    def test_unknown_delivery_consumes_slot_and_cannot_auto_retry(self):
        for n in range(3):
            event = self.event(n)
            publication = NewsPublication(event=event, target=self.target, status="uncertain")
            with transaction.atomic():
                self.assertTrue(reserve_day(publication, self.config))
                publication.save()
        event = self.event(4)
        with transaction.atomic():
            self.assertFalse(reserve_day(NewsPublication(event=event, target=self.target), self.config))

    def test_low_score_and_expired_events_not_selected(self):
        self.event("low", score=10)
        event = self.event("old")
        event.expires_at = self.now-timedelta(seconds=1)
        event.save()
        self.assertIsNone(select_publication())

    def test_same_release_merges_across_posts_and_wording(self):
        payload = AssessmentPayload(relevant=True, product="Codex", version="1.0", event_type="tool_release",
            event_key="first-announcement", confirmed=True, urgent=True, score=90, reason="Релиз",
            facts=[Fact(text="Добавлена проверка кода.", evidence="Codex adds code review.")], related_event_id=None)
        with transaction.atomic():
            save_event(self.post(), payload, self.config)
            save_event(self.post("992"), payload.model_copy(update={"event_key": "other-wording"}), self.config)
        self.assertEqual(NewsEvent.objects.count(), 1)
        self.assertEqual(NewsEvent.objects.get().evidence.count(), 2)

    def test_fact_evidence_must_exist_in_original(self):
        payload = AssessmentPayload(relevant=True, product="Codex", version="", event_type="feature",
            event_key="review", confirmed=True, urgent=False, score=80, reason="Функция",
            facts=[Fact(text="Бесплатно.", evidence="Free for everyone")], related_event_id=None)
        with self.assertRaises(ValueError):
            validate_assessment(payload, self.post())

    def test_editorial_floor_rejects_truncated_thin_and_repeating_texts(self):
        body = "Обновление добавляет разбор кода и заметно ускоряет проверку. " * 5
        with self.assertRaises(ValueError):
            editorial(WritingPayload(title="К"*121, text=body))
        with self.assertRaises(ValueError):
            editorial(WritingPayload(title="Обновление Codex", text="Запуск Codex."))
        with self.assertRaises(ValueError):
            editorial(WritingPayload(title="Обновление Codex", text="Обновление Codex. "+body))
        editorial(WritingPayload(title="Обновление Codex", text=body))

    def test_render_escapes_text_and_uses_only_real_source_links(self):
        post = self.post()
        body = " Проверка кода и изменения в разборе, ускорение и новые настройки для команд."*3
        text = render(WritingPayload(title="Codex <обновился>", text="Разбор & правки."+body), [post])
        self.assertIn("&lt;обновился&gt;", text)
        self.assertIn(post.source_url, text)
        # Only the original source is credited; the publication carries no date line.
        self.assertNotIn(post.published_at.strftime("%Y"), text)
        self.assertTrue(text.rstrip().endswith("</a>"))
        with self.assertRaises(ValueError):
            render(WritingPayload(title="Обновление Codex", text="Подробнее https://invented.example"+body), [post])

    def test_resolution_requires_operator_note_and_message_ids(self):
        publication = NewsPublication.objects.create(event=self.event(1), target=self.target, status="uncertain")
        receipt = NewsDelivery.objects.create(publication=publication)
        with self.assertRaises(ValueError):
            resolve(receipt.pk, was_sent=False, note="")
        with self.assertRaises(ValueError):
            resolve(receipt.pk, was_sent=True, note="Проверил канал")
        resolve(receipt.pk, was_sent=False, note="Проверил: сообщения нет")
        publication.refresh_from_db()
        self.assertEqual(publication.status, "ready")

    def test_news_cannot_target_private_chat_or_exceed_daily_cap(self):
        self.config.daily_limit = 4
        with self.assertRaises(ValidationError):
            self.config.full_clean()
        with self.assertRaises(ValidationError):
            DeliveryTarget(target_type="private_chat", feed="news", telegram_chat_id="123").full_clean()

class TransportPolicyTests(SimpleTestCase):
    def test_receipt_requires_all_album_message_ids(self):
        body = {"ok": True, "result": [{"message_id": 1}, {"message_id": 2}]}
        self.assertEqual(parse_receipt(200, body, 2), ["1", "2"])
        with self.assertRaises(DeliveryUncertain):
            parse_receipt(200, body, 3)
        with self.assertRaises(DeliveryUncertain):
            parse_receipt(502, {}, 1)
        with self.assertRaises(DeliveryRateLimited):
            parse_receipt(429, {"ok": False, "error_code": 429, "parameters": {"retry_after": 9}}, 1)
        with self.assertRaises(DeliveryRejected):
            parse_receipt(403, {"ok": False, "error_code": 403}, 1)

    def test_media_url_and_original_video_rules(self):
        for url in ("https://localhost/a", "http://video.twimg.com/a", "https://video.twimg.com.evil/a"):
            with self.assertRaises(ValueError):
                validate_url(url)
        post = SimpleNamespace(raw_data={"post": {"attachments": {"media_keys": ["v"]}},
            "includes": {"media": [{"media_key": "v", "type": "video",
                                   "preview_image_url": "https://pbs.twimg.com/preview.jpg"}]}})
        with self.assertRaises(ValueError):
            attachment_plan(post)
        post.raw_data["includes"]["media"][0]["variants"] = [
            {"content_type": "video/mp4", "bit_rate": 128, "url": "https://video.twimg.com/low.mp4"},
            {"content_type": "video/mp4", "bit_rate": 256, "url": "https://video.twimg.com/high.mp4"}]
        self.assertEqual(attachment_plan(post), [("v", "video", "https://video.twimg.com/high.mp4")])

    def test_search_filter_cannot_escape_allowlisted_account(self):
        subscription = SimpleNamespace(source=SimpleNamespace(username="OpenAI"), query_terms="Codex GPT")
        self.assertEqual(build_query(subscription), "from:OpenAI -is:retweet (Codex OR GPT)")
        subscription.query_terms = "Codex) OR from:unknown"
        with self.assertRaises(ValueError):
            build_query(subscription)
