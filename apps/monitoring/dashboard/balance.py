"""Cached X credit balance for the status strip; failures never imply zero credit."""
from __future__ import annotations

import logging

from django.core.cache import cache

from apps.monitoring.x_api import XApiClient, XApiError

logger = logging.getLogger(__name__)
_CACHE_KEY = "monitoring:x-credit-balance:v1"
_SUCCESS_TTL_SECONDS = 300
_FAILURE_TTL_SECONDS = 60
UNAVAILABLE = "Недоступен"


def load_x_balance() -> str:
    cached = cache.get(_CACHE_KEY)
    if cached is not None:
        return cached
    try:
        with XApiClient(timeout_seconds=5) as client:
            amount = client.get_credit_balance()
        display = f"${amount:.2f}"
        timeout = _SUCCESS_TTL_SECONDS
    except XApiError as exc:
        logger.warning("X credit balance is unavailable.", extra={"error_type": type(exc).__name__})
        display, timeout = UNAVAILABLE, _FAILURE_TTL_SECONDS
    cache.set(_CACHE_KEY, display, timeout=timeout)
    return display
