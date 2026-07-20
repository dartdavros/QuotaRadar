from django.test import SimpleTestCase

from quotaradar.database import (
    DatabaseUrlError,
    database_config_from_environment,
    parse_database_url,
)


class ParseDatabaseUrlTests(SimpleTestCase):
    def test_parses_postgresql_url_and_options(self) -> None:
        config = parse_database_url(
            "postgresql://quota%20user:secret%2Fvalue@db:5433/quota_db?sslmode=require"
        )

        self.assertEqual(config["ENGINE"], "django.db.backends.postgresql")
        self.assertEqual(config["NAME"], "quota_db")
        self.assertEqual(config["USER"], "quota user")
        self.assertEqual(config["PASSWORD"], "secret/value")
        self.assertEqual(config["HOST"], "db")
        self.assertEqual(config["PORT"], "5433")
        self.assertEqual(config["OPTIONS"], {"sslmode": "require"})

    def test_parses_in_memory_sqlite_url_for_tests(self) -> None:
        config = parse_database_url("sqlite:///:memory:")

        self.assertEqual(config["ENGINE"], "django.db.backends.sqlite3")
        self.assertEqual(config["NAME"], ":memory:")

    def test_rejects_unsupported_scheme(self) -> None:
        with self.assertRaises(DatabaseUrlError):
            parse_database_url("mysql://db/quota")


class DatabaseEnvironmentTests(SimpleTestCase):
    def test_builds_postgresql_config_from_discrete_variables(self) -> None:
        config = database_config_from_environment(
            {
                "POSTGRES_DB": "quota",
                "POSTGRES_USER": "quota-user",
                "POSTGRES_PASSWORD": "p@ss/word",
                "POSTGRES_HOST": "postgres",
                "POSTGRES_PORT": "5433",
            }
        )

        self.assertEqual(config["NAME"], "quota")
        self.assertEqual(config["USER"], "quota-user")
        self.assertEqual(config["PASSWORD"], "p@ss/word")
        self.assertEqual(config["HOST"], "postgres")
        self.assertEqual(config["PORT"], "5433")

    def test_database_url_has_precedence(self) -> None:
        config = database_config_from_environment(
            {
                "DATABASE_URL": "sqlite:///:memory:",
                "POSTGRES_DB": "ignored",
            }
        )

        self.assertEqual(config["ENGINE"], "django.db.backends.sqlite3")

    def test_rejects_incomplete_discrete_configuration(self) -> None:
        with self.assertRaises(DatabaseUrlError):
            database_config_from_environment({"POSTGRES_DB": "quota"})
