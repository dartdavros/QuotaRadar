"""Quota-reset deliveries: a source post older than thirty minutes is never sent (covers polling plus analysis)."""
from datetime import timedelta

MAX_EVENT_AGE = timedelta(minutes=30)


def stale(published_at, now):
    return published_at + MAX_EVENT_AGE <= now
