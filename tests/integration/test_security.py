from __future__ import annotations

from unittest import skipUnless

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TransactionTestCase

from apps.secrets.models import SecretCode
from apps.secrets.services import set_secret


@skipUnless(connection.vendor == "postgresql", "PostgreSQL integration test")
class PostgreSqlCiphertextTests(TransactionTestCase):
    reset_sequences = True

    def test_plaintext_is_absent_from_raw_database_column(self) -> None:
        user = get_user_model().objects.create_user(username="cipher-auditor")
        plaintext = "postgres-raw-column-secret-value"
        set_secret(SecretCode.LLM_API_KEY, plaintext, updated_by=user)

        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT encrypted_value FROM secrets_encryptedsecret WHERE code = %s",
                [SecretCode.LLM_API_KEY],
            )
            row = cursor.fetchone()

        self.assertIsNotNone(row)
        ciphertext = bytes(row[0])
        self.assertNotIn(plaintext.encode("utf-8"), ciphertext)
