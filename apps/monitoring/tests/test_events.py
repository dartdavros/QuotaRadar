from django.test import TestCase

from apps.monitoring.events import record_monitoring_event
from apps.monitoring.models import (
    MonitoringComponent,
    MonitoringEvent,
    MonitoringEventStatus,
)
from apps.secrets.redaction import clear_registered_values, register_sensitive_value
from apps.sources.models import Source


class MonitoringEventTests(TestCase):
    def tearDown(self) -> None:
        clear_registered_values()

    def test_event_message_is_redacted_before_persistence(self) -> None:
        source = Source.objects.get(username="OpenAIDevs")
        register_sensitive_value("secret-token")

        record_monitoring_event(
            component=MonitoringComponent.X,
            status=MonitoringEventStatus.ERROR,
            source=source,
            message="Request failed with secret-token",
            error_type="ExampleError",
            task_id="task-1",
        )

        event = MonitoringEvent.objects.get()
        self.assertEqual(event.message, "Request failed with ***")
        self.assertEqual(event.error_type, "ExampleError")
        self.assertEqual(event.task_id, "task-1")
