from django.test import SimpleTestCase

from apps.monitoring.tasks import healthcheck


class HealthcheckTaskTests(SimpleTestCase):
    def test_returns_worker_status(self) -> None:
        self.assertEqual(
            healthcheck.run(),
            {"status": "ok", "service": "worker"},
        )
