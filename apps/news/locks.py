"""Serialize sending and local cache preparation without database locks over HTTP."""
from contextlib import contextmanager
from django.conf import settings
from redis import Redis
from redis.exceptions import LockError

@contextmanager
def publication_lock(publication_id):
    client = Redis.from_url(settings.REDIS_URL)
    lock = client.lock(f"quotaradar:news:publication:{publication_id}", timeout=1800, blocking_timeout=0)
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
