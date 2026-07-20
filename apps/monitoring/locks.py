"""Redis-backed concurrency control for source polling."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from django.conf import settings
from redis import Redis
from redis.exceptions import LockError

_SOURCE_LOCK_TIMEOUT_SECONDS = 1800


@contextmanager
def source_poll_lock(source_id: int) -> Iterator[bool]:
    """Yield whether the non-blocking lock for one source was acquired."""

    client = Redis.from_url(settings.REDIS_URL, decode_responses=False)
    lock = client.lock(
        f"quotaradar:monitoring:source:{source_id}",
        timeout=_SOURCE_LOCK_TIMEOUT_SECONDS,
        blocking_timeout=0,
    )
    acquired = False
    try:
        acquired = bool(lock.acquire(blocking=False))
        yield acquired
    finally:
        if acquired:
            try:
                lock.release()
            except LockError:
                pass
        client.close()
