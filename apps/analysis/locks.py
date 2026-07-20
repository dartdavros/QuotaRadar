"""Redis-backed concurrency control for one-post LLM analysis."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from django.conf import settings
from redis import Redis
from redis.exceptions import LockError

_ANALYSIS_LOCK_TIMEOUT_SECONDS = 3600


@contextmanager
def source_post_analysis_lock(source_post_id: int) -> Iterator[bool]:
    """Yield whether the non-blocking analysis lock was acquired."""

    client = Redis.from_url(settings.REDIS_URL, decode_responses=False)
    lock = client.lock(
        f"quotaradar:analysis:source-post:{source_post_id}",
        timeout=_ANALYSIS_LOCK_TIMEOUT_SECONDS,
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
