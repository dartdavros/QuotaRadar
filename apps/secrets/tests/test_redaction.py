import logging

from django.test import SimpleTestCase

from apps.secrets.redaction import (
    SafeFormatter,
    clear_registered_values,
    redact_text,
    register_sensitive_value,
)


class RedactionTests(SimpleTestCase):
    def tearDown(self) -> None:
        clear_registered_values()

    def test_redacts_registered_secret_and_proxy_credentials(self) -> None:
        token = "secret-token-value"
        register_sensitive_value(token)

        output = redact_text(
            f"token={token} proxy=http://user:password@proxy.example:8080"
        )

        self.assertNotIn(token, output)
        self.assertNotIn("user", output)
        self.assertNotIn("password", output)
        self.assertIn("http://***:***@proxy.example:8080", output)

    def test_registered_proxy_url_is_removed_completely(self) -> None:
        proxy_url = "http://user:password@private-proxy.example:8080"
        register_sensitive_value(proxy_url)

        output = redact_text(f"proxy={proxy_url}")

        self.assertNotIn("private-proxy.example", output)
        self.assertEqual(output, "proxy=***")

    def test_formatter_redacts_exception_traceback(self) -> None:
        token = "traceback-secret"
        register_sensitive_value(token)
        formatter = SafeFormatter("%(levelname)s %(message)s")
        try:
            raise RuntimeError(f"request failed with {token}")
        except RuntimeError:
            record = logging.LogRecord(
                name="test",
                level=logging.ERROR,
                pathname=__file__,
                lineno=1,
                msg="failure",
                args=(),
                exc_info=__import__("sys").exc_info(),
            )

        output = formatter.format(record)
        self.assertNotIn(token, output)
        self.assertIn("***", output)
