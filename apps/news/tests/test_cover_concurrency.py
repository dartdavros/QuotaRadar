"""PostgreSQL prevents two preparation workers from issuing the same paid image request."""
from concurrent.futures import ThreadPoolExecutor
from unittest import skipUnless

from django.db import close_old_connections, connection, connections
from django.test import TransactionTestCase

from apps.news.cover_client import CoverBlocked
from apps.news.covers import claim_generation
from apps.news.models import NewsConfiguration, NewsPublication
from .cover_cases import make_publication


@skipUnless(connection.vendor == "postgresql", "Paid request claims require PostgreSQL row locks.")
class CoverConcurrencyTests(TransactionTestCase):
    serialized_rollback = True

    def test_only_one_concurrent_worker_can_claim_a_paid_request(self):
        publication, _, _, _, _ = make_publication()

        def claim():
            close_old_connections()
            try:
                return claim_generation(NewsPublication.objects.get(pk=publication.pk), NewsConfiguration.load())
            except CoverBlocked:
                return False
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=4) as pool:
            outcomes = list(pool.map(lambda _: claim(), range(4)))
        self.assertEqual(sum(outcomes), 1)
        publication.refresh_from_db()
        self.assertIsNotNone(publication.cover_requested_at)
