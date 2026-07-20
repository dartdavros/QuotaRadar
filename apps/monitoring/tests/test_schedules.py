from django.test import TestCase

from apps.configuration.models import SystemConfiguration
from apps.monitoring.schedules import DatabasePollingSchedule


class DatabasePollingScheduleTests(TestCase):
    def test_reads_poll_interval_from_system_configuration(self) -> None:
        configuration = SystemConfiguration.load()
        configuration.poll_interval_seconds = 123
        configuration.save()

        schedule = DatabasePollingSchedule()

        self.assertEqual(schedule._load_interval_seconds(), 123)
