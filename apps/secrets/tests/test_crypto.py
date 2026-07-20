import json
from pathlib import Path
from tempfile import TemporaryDirectory

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from apps.secrets.crypto import SecretDecryptionError
from apps.secrets.models import EncryptedSecret, SecretCode
from apps.secrets.services import get_secret, set_secret


class SecretServiceTests(TestCase):
    def setUp(self) -> None:
        self.user = get_user_model().objects.create_user(
            username="admin",
            password="test-password",
        )

    def test_stores_ciphertext_and_round_trips_plaintext(self) -> None:
        plaintext = "x-api-key-super-secret"

        set_secret(SecretCode.LLM_API_KEY, plaintext, updated_by=self.user)

        record = EncryptedSecret.objects.get(code=SecretCode.LLM_API_KEY)
        self.assertNotIn(plaintext.encode(), bytes(record.encrypted_value))
        self.assertEqual(record.key_version, "v1")
        self.assertEqual(record.updated_by, self.user)
        self.assertEqual(get_secret(SecretCode.LLM_API_KEY), plaintext)

    def test_wrong_master_key_never_returns_corrupted_value(self) -> None:
        with TemporaryDirectory() as directory:
            key_file = Path(directory) / "master.key"
            key_file.write_text("first-key-material", encoding="utf-8")
            with override_settings(QUOTARADAR_MASTER_KEY_FILE=key_file):
                set_secret(
                    SecretCode.X_BEARER_TOKEN, "token-value", updated_by=self.user
                )
                key_file.write_text("different-key-material", encoding="utf-8")

                with self.assertRaises(SecretDecryptionError):
                    get_secret(SecretCode.X_BEARER_TOKEN)

    def test_keyring_rotation_keeps_old_ciphertext_readable(self) -> None:
        with TemporaryDirectory() as directory:
            key_file = Path(directory) / "master.key"
            key_file.write_text(
                json.dumps(
                    {
                        "active_version": "v1",
                        "keys": {"v1": "old-key-material"},
                    }
                ),
                encoding="utf-8",
            )
            with override_settings(QUOTARADAR_MASTER_KEY_FILE=key_file):
                set_secret(
                    SecretCode.TELEGRAM_BOT_TOKEN, "old-token", updated_by=self.user
                )
                key_file.write_text(
                    json.dumps(
                        {
                            "active_version": "v2",
                            "keys": {
                                "v1": "old-key-material",
                                "v2": "new-key-material",
                            },
                        }
                    ),
                    encoding="utf-8",
                )

                self.assertEqual(
                    get_secret(SecretCode.TELEGRAM_BOT_TOKEN),
                    "old-token",
                )
                set_secret(
                    SecretCode.TELEGRAM_BOT_TOKEN,
                    "new-token",
                    updated_by=self.user,
                )

        record = EncryptedSecret.objects.get(code=SecretCode.TELEGRAM_BOT_TOKEN)
        self.assertEqual(record.key_version, "v2")
