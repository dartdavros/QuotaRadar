import json
import logging

from django.test import SimpleTestCase

from apps.configuration.logging import JsonLogFormatter
from apps.secrets.redaction import clear_registered_values, register_sensitive_value


class JsonLogFormatterTests(SimpleTestCase):
    def tearDown(self) -> None:
        clear_registered_values()

    def test_emits_structured_context_and_redacts_final_payload(self) -> None:
        secret = "sensitive-token-value"
        register_sensitive_value(secret)
        record = logging.LogRecord(
            name="quotaradar.test",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="delivery token=%s",
            args=(secret,),
            exc_info=None,
        )
        record.event = "telegram.delivery_completed"
        record.task_id = "task-1"
        record.source_id = 2
        record.x_post_id = "9001"
        record.analysis_id = 3
        record.delivery_target_id = 4
        record.delivery_id = 5
        record.status = "sent"

        payload = json.loads(JsonLogFormatter().format(record))

        self.assertEqual(payload["event"], "telegram.delivery_completed")
        self.assertEqual(payload["task_id"], "task-1")
        self.assertEqual(payload["source_id"], 2)
        self.assertEqual(payload["delivery_id"], 5)
        self.assertEqual(payload["status"], "sent")
        self.assertNotIn(secret, payload["message"])
        self.assertIn("***", payload["message"])
