"""Consecutive LLM failures counted in Redis, because four workers share the verdict."""

from __future__ import annotations

from django.conf import settings
from redis import Redis
from redis.exceptions import RedisError

CONSECUTIVE_FAILURES_KEY = "quotaradar:analysis:llm-consecutive-failures"
FALLBACK_THRESHOLD = 2
_COUNTER_TTL_SECONDS = 86_400


def record_llm_failure() -> int:
    """Count one failed LLM call and return the current consecutive total."""

    client = Redis.from_url(settings.REDIS_URL, decode_responses=False)
    try:
        total = int(client.incr(CONSECUTIVE_FAILURES_KEY))
        client.expire(CONSECUTIVE_FAILURES_KEY, _COUNTER_TTL_SECONDS)
        return total
    except RedisError:
        # The counter is an optimization, not a source of truth: a Redis hiccup
        # must not turn one LLM error into a failed analysis task.
        return 0
    finally:
        client.close()


def record_llm_success() -> None:
    """Clear the counter so only uninterrupted failures reach the threshold."""

    client = Redis.from_url(settings.REDIS_URL, decode_responses=False)
    try:
        client.delete(CONSECUTIVE_FAILURES_KEY)
    except RedisError:
        pass
    finally:
        client.close()


def llm_unavailable() -> bool:
    """Report whether the LLM failed at least :data:`FALLBACK_THRESHOLD` times in a row."""

    client = Redis.from_url(settings.REDIS_URL, decode_responses=False)
    try:
        raw = client.get(CONSECUTIVE_FAILURES_KEY)
        return raw is not None and int(raw) >= FALLBACK_THRESHOLD
    except (RedisError, TypeError, ValueError):
        return False
    finally:
        client.close()
