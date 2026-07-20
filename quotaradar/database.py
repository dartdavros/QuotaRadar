"""Database configuration kept independent from Django settings."""

from __future__ import annotations

from collections.abc import Mapping
from urllib.parse import parse_qsl, unquote, urlparse


class DatabaseUrlError(ValueError):
    """Raised when database bootstrap settings are invalid."""


def parse_database_url(value: str) -> dict[str, object]:
    """Convert a PostgreSQL or SQLite URL to Django DATABASES format."""
    if not value:
        raise DatabaseUrlError("DATABASE_URL must not be empty.")

    parsed = urlparse(value)
    scheme = parsed.scheme.lower()

    if scheme in {"postgres", "postgresql"}:
        if not parsed.hostname or not parsed.path or parsed.path == "/":
            raise DatabaseUrlError(
                "PostgreSQL DATABASE_URL must contain a host and database name."
            )

        options = dict(parse_qsl(parsed.query, keep_blank_values=True))
        config: dict[str, object] = {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": unquote(parsed.path.lstrip("/")),
            "USER": unquote(parsed.username or ""),
            "PASSWORD": unquote(parsed.password or ""),
            "HOST": parsed.hostname,
            "PORT": str(parsed.port or 5432),
            "CONN_MAX_AGE": 60,
            "CONN_HEALTH_CHECKS": True,
        }
        if options:
            config["OPTIONS"] = options
        return config

    if scheme == "sqlite":
        if value == "sqlite:///:memory:":
            name = ":memory:"
        else:
            name = unquote(parsed.path)
            if not name:
                raise DatabaseUrlError(
                    "SQLite DATABASE_URL must contain a database path."
                )
        return {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": name,
        }

    raise DatabaseUrlError(
        "DATABASE_URL must use postgresql://, postgres:// or sqlite://."
    )


def database_config_from_environment(
    environment: Mapping[str, str],
) -> dict[str, object]:
    """Build database settings from DATABASE_URL or discrete PostgreSQL values."""

    database_url = environment.get("DATABASE_URL", "").strip()
    if database_url:
        return parse_database_url(database_url)

    required_names = (
        "POSTGRES_DB",
        "POSTGRES_USER",
        "POSTGRES_PASSWORD",
        "POSTGRES_HOST",
    )
    values = {name: environment.get(name, "").strip() for name in required_names}
    missing = [name for name, value in values.items() if not value]
    if missing:
        joined = ", ".join(missing)
        raise DatabaseUrlError(
            "Database configuration is incomplete; missing environment variables: "
            f"{joined}."
        )

    port = environment.get("POSTGRES_PORT", "5432").strip() or "5432"
    try:
        parsed_port = int(port)
    except ValueError:
        raise DatabaseUrlError("POSTGRES_PORT must be an integer.") from None
    if not 1 <= parsed_port <= 65535:
        raise DatabaseUrlError("POSTGRES_PORT must be between 1 and 65535.")

    return {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": values["POSTGRES_DB"],
        "USER": values["POSTGRES_USER"],
        "PASSWORD": values["POSTGRES_PASSWORD"],
        "HOST": values["POSTGRES_HOST"],
        "PORT": str(parsed_port),
        "CONN_MAX_AGE": 60,
        "CONN_HEALTH_CHECKS": True,
    }
