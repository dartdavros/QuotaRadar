"""Two consecutive LLM failures, counted across workers, open the fallback."""

from __future__ import annotations

from django.test import TestCase
from redis import Redis
from django.conf import settings

from apps.analysis.availability import (
    CONSECUTIVE_FAILURES_KEY,
    record_llm_failure,
    record_llm_success,
    llm_unavailable,
)


class LlmAvailabilityTests(TestCase):
    def setUp(self) -> None:
        self.addCleanup(self._clear)
        self._clear()

    @staticmethod
    def _clear() -> None:
        client = Redis.from_url(settings.REDIS_URL, decode_responses=False)
        try:
            client.delete(CONSECUTIVE_FAILURES_KEY)
        finally:
            client.close()

    def test_one_failure_is_not_enough(self) -> None:
        self.assertEqual(record_llm_failure(), 1)
        self.assertFalse(llm_unavailable())

    def test_two_consecutive_failures_open_the_fallback(self) -> None:
        record_llm_failure()
        self.assertEqual(record_llm_failure(), 2)
        self.assertTrue(llm_unavailable())

    def test_success_clears_the_counter(self) -> None:
        record_llm_failure()
        record_llm_failure()
        record_llm_success()

        self.assertFalse(llm_unavailable())
        self.assertEqual(record_llm_failure(), 1)

    def test_unavailable_is_false_without_any_failure(self) -> None:
        self.assertFalse(llm_unavailable())
