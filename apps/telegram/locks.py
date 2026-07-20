"""Redis-backed concurrency control for Telegram deliveries."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from django.conf import settings
from redis import Redis
from redis.exceptions import LockError

_DELIVERY_LOCK_TIMEOUT_SECONDS = 300


@contextmanager
def delivery_send_lock(delivery_id: int) -> Iterator[bool]:
    """Yield whether the non-blocking lock for one delivery was acquired."""

    client = Redis.from_url(settings.REDIS_URL, decode_responses=False)
    lock = client.lock(
        f"quotaradar:telegram:delivery:{delivery_id}",
        timeout=_DELIVERY_LOCK_TIMEOUT_SECONDS,
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
