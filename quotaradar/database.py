"""Database URL parsing kept independent from Django settings."""

from __future__ import annotations

from urllib.parse import parse_qsl, unquote, urlparse


class DatabaseUrlError(ValueError):
    """Raised when DATABASE_URL cannot be converted into Django settings."""


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
