from unittest.mock import Mock, patch

from django.test import SimpleTestCase

from apps.monitoring.locks import source_poll_lock


class SourcePollLockTests(SimpleTestCase):
    @patch("apps.monitoring.locks.Redis.from_url")
    def test_uses_non_blocking_per_source_redis_lock(self, from_url: Mock) -> None:
        client = from_url.return_value
        lock = client.lock.return_value
        lock.acquire.return_value = True

        with source_poll_lock(42) as acquired:
            self.assertTrue(acquired)

        client.lock.assert_called_once_with(
            "quotaradar:monitoring:source:42",
            timeout=1800,
            blocking_timeout=0,
        )
        lock.acquire.assert_called_once_with(blocking=False)
        lock.release.assert_called_once_with()
        client.close.assert_called_once_with()
