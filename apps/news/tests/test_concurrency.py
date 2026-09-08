"""Exercise the weekly cap against concurrent PostgreSQL transactions."""
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from unittest import skipUnless
from django.db import connection, connections, close_old_connections
from django.test import TransactionTestCase
from apps.news.budget import reserve, BudgetExhausted
from apps.news.models import NewsConfiguration, XBudgetPeriod
from apps.sources.models import Source

@skipUnless(connection.vendor == "postgresql", "Row locking requires PostgreSQL.")
class BudgetConcurrencyTests(TransactionTestCase):
    serialized_rollback = True
    def test_concurrent_workers_cannot_overspend(self):
        source = Source.objects.create(provider="openai", username="budget_test")
        config = NewsConfiguration.objects.first()
        if config is None:
            config = NewsConfiguration.objects.create()
        config.weekly_x_limit = Decimal(".100")
        config.save()
        def request():
            close_old_connections()
            try:
                reserve(Source.objects.get(pk=source.pk), NewsConfiguration.load(),
                        maximum=Decimal(".050"), priority=True)
                return True
            except BudgetExhausted:
                return False
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=4) as pool:
            outcomes = list(pool.map(lambda _: request(), range(4)))
        self.assertEqual(sum(outcomes), 2)
        self.assertEqual(XBudgetPeriod.objects.get().committed, Decimal(".100"))


    def test_concurrent_fill_reservations_cannot_exceed_two_dollars(self):
        from datetime import timedelta
        from django.utils import timezone
        from apps.news.models import InitialFill
        from apps.telegram.models import DeliveryTarget
        source = Source.objects.create(provider="openai", username="fill_budget")
        config = NewsConfiguration.load()
        target = DeliveryTarget.objects.create(target_type="channel", feed="news", telegram_chat_id="-100889")
        now = timezone.now()
        run = InitialFill.objects.create(target=target, status="collecting",
            window_start=now-timedelta(days=3), window_end=now, expires_at=now+timedelta(hours=24))
        reserve(source, config, maximum=Decimal("1.950"), priority=True, initial_fill_id=run.pk)

        def request():
            close_old_connections()
            try:
                reserve(Source.objects.get(pk=source.pk), NewsConfiguration.load(),
                        maximum=Decimal(".050"), priority=True, initial_fill_id=run.pk)
                return True
            except BudgetExhausted:
                return False
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=4) as pool:
            outcomes = list(pool.map(lambda _: request(), range(4)))
        self.assertEqual(sum(outcomes), 1)
        run.refresh_from_db()
        self.assertEqual(run.committed, Decimal("2"))
        self.assertEqual(XBudgetPeriod.objects.get().committed, Decimal("2"))
