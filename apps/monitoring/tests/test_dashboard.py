"""The health panel must name the broken component and link to where it is fixed."""
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from apps.configuration.models import SystemConfiguration
from apps.monitoring.dashboard import build_dashboard
from apps.monitoring.dashboard.report import ERROR, OFF, OK, WARN
from apps.monitoring.events import record_monitoring_event
from apps.monitoring.models import MonitoringComponent, MonitoringEventStatus
from apps.news.models import CollectionCheckpoint, NewsConfiguration, XBudgetPeriod
from apps.sources.models import Feed, Source
from apps.telegram.models import DeliveryTarget
from tests._otp import force_login_verified

WORKERS = {"celery@web": "pong", "news-default@web": "pong", "news-urgent@web": "pong"}


def by_title(dashboard, title):
    return next(check for check in dashboard.checks if check.title == title)


@patch("apps.monitoring.dashboard.workers.ping_workers", return_value=WORKERS)
class HealthPanelTests(TestCase):
    def setUp(self):
        self.now = timezone.now()
        self.config = SystemConfiguration.load()
        self.config.monitoring_enabled = True
        self.config.llm_provider, self.config.llm_model = "openai", "gpt"
        self.config.save()
        DeliveryTarget.objects.create(target_type="private_chat", feed=Feed.QUOTA, telegram_chat_id="1")
        Source.objects.filter(enabled=True).update(last_checked_at=self.now, last_success_at=self.now, last_error="")

    def test_everything_green_when_nothing_is_wrong(self, _ping):
        dashboard = build_dashboard()
        self.assertEqual(dashboard.level, OK)
        self.assertEqual(dashboard.headline, "ВСЁ РАБОТАЕТ")
        self.assertEqual(by_title(dashboard, "Сбор новостей").level, OFF)
        self.assertEqual(dashboard.errors, [])

    def test_source_error_is_named_with_its_message(self, _ping):
        source = Source.objects.get(username="OpenAIDevs")
        source.last_error = "X API returned 401"
        source.last_checked_at = self.now
        source.last_success_at = self.now - timedelta(hours=1)
        source.save()
        check = by_title(build_dashboard(), "Опрос X (лимиты)")
        self.assertEqual(check.level, ERROR)
        self.assertIn("@OpenAIDevs: X API returned 401", check.summary)
        self.assertIn("/admin/sources/source/", check.links[0].url)

    def test_dead_scheduler_is_reported(self, _ping):
        Source.objects.update(last_checked_at=self.now - timedelta(hours=2))
        dashboard = build_dashboard()
        self.assertEqual(by_title(dashboard, "Планировщик (beat)").level, ERROR)
        self.assertEqual(dashboard.level, ERROR)
        self.assertTrue(dashboard.headline.startswith("НЕ РАБОТАЕТ"))

    def test_missing_worker_and_error_feed(self, ping):
        ping.return_value = {"celery@web": "pong"}
        record_monitoring_event(component=MonitoringComponent.TELEGRAM, status=MonitoringEventStatus.ERROR,
                                message="chat not found", error_type="TelegramPermanentChatError")
        dashboard = build_dashboard()
        workers = by_title(dashboard, "Воркеры Celery")
        self.assertEqual(workers.level, ERROR)
        self.assertIn("news-worker", workers.summary)
        self.assertEqual(dashboard.errors[0].error_type, "TelegramPermanentChatError")
        self.assertIn("chat not found", by_title(dashboard, "Telegram (лимиты)").last_error)

    def test_news_budget_follows_the_setting_not_the_frozen_week(self, _ping):
        news = NewsConfiguration.load()
        news.collection_enabled, news.weekly_x_limit = True, "5.000"
        news.save()
        XBudgetPeriod.objects.create(week=self.now.date(), limit="3.000", committed="2.995")
        point = CollectionCheckpoint.objects.create(source=Source.objects.get(username="OpenAIDevs"),
            last_error="Бюджет X исчерпан.", next_attempt_at=self.now + timedelta(minutes=12))
        check = by_title(build_dashboard(), "Сбор новостей")
        self.assertIn("2.995 из 5.000", check.details[0])
        self.assertIn("Повтор через 1", check.summary)
        self.assertEqual(check.level, WARN)

    def test_disabled_monitoring_is_off_not_broken(self, _ping):
        self.config.monitoring_enabled = False
        self.config.save()
        dashboard = build_dashboard()
        self.assertEqual(by_title(dashboard, "Опрос X (лимиты)").level, OFF)
        self.assertNotEqual(dashboard.level, ERROR)

    def test_admin_index_renders_the_panel(self, _ping):
        user = get_user_model().objects.create_superuser("owner", "owner@example.com", "pass-for-tests-only")
        force_login_verified(self.client, user)
        response = self.client.get("/admin/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="health-panel"')
        self.assertContains(response, "ВСЁ РАБОТАЕТ")
        self.assertContains(response, "Опрос X (лимиты)")
        self.assertNotContains(response, "Последние действия")

    def test_broken_check_does_not_take_the_page_down(self, _ping):
        with patch("apps.monitoring.dashboard.check_x_polling", side_effect=RuntimeError("boom")):
            dashboard = build_dashboard()
        self.assertEqual(dashboard.level, ERROR)
        self.assertIn("boom", next(c for c in dashboard.checks if c.level == ERROR).summary)
