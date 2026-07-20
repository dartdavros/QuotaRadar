"""Bootstrap dependency checks used by all application processes."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from django.db import connections
from redis import Redis

from apps.secrets.keyring import MasterKeyError, load_master_keyring


class DependencyCheckError(RuntimeError):
    """Raised when a required bootstrap dependency is unavailable."""


@dataclass(frozen=True, slots=True)
class DependencyStatus:
    database: bool
    redis: bool
    master_key: bool


def check_database(alias: str = "default") -> None:
    try:
        connection = connections[alias]
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            row = cursor.fetchone()
    except Exception as exc:
        raise DependencyCheckError("PostgreSQL connection check failed.") from exc

    if row != (1,):
        raise DependencyCheckError(
            "PostgreSQL connection check returned an invalid result."
        )


def check_redis(redis_url: str) -> None:
    client = Redis.from_url(
        redis_url,
        socket_connect_timeout=3,
        socket_timeout=3,
        decode_responses=False,
    )
    try:
        is_available = client.ping()
    except Exception as exc:
        raise DependencyCheckError("Redis connection check failed.") from exc
    finally:
        client.close()

    if is_available is not True:
        raise DependencyCheckError("Redis connection check returned an invalid result.")


def check_master_key(path: Path) -> None:
    if not path.is_file():
        raise DependencyCheckError("Master key file does not exist or is not a file.")
    try:
        load_master_keyring(path)
    except MasterKeyError as exc:
        raise DependencyCheckError(str(exc)) from exc


def check_dependencies(*, redis_url: str, master_key_file: Path) -> DependencyStatus:
    check_database()
    check_redis(redis_url)
    check_master_key(master_key_file)
    return DependencyStatus(database=True, redis=True, master_key=True)
