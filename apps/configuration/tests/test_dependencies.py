from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from django.test import SimpleTestCase

from apps.configuration.dependencies import (
    DependencyCheckError,
    check_master_key,
    check_redis,
)


class MasterKeyCheckTests(SimpleTestCase):
    def test_accepts_non_empty_readable_file(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "master.key"
            path.write_text("test-only-key", encoding="utf-8")

            check_master_key(path)

    def test_rejects_empty_file(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "master.key"
            path.touch()

            with self.assertRaisesMessage(DependencyCheckError, "empty"):
                check_master_key(path)

    def test_rejects_missing_file(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "missing.key"

            with self.assertRaisesMessage(DependencyCheckError, "does not exist"):
                check_master_key(path)


class RedisCheckTests(SimpleTestCase):
    @patch("apps.configuration.dependencies.Redis.from_url")
    def test_pings_and_closes_client(self, from_url: Mock) -> None:
        client = from_url.return_value
        client.ping.return_value = True

        check_redis("redis://redis:6379/0")

        from_url.assert_called_once()
        client.ping.assert_called_once_with()
        client.close.assert_called_once_with()
