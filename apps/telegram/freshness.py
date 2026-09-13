"""One rule for every Telegram feed: an event older than five minutes is never sent."""
from datetime import timedelta

MAX_EVENT_AGE = timedelta(minutes=5)


def stale(published_at, now):
    return published_at + MAX_EVENT_AGE <= now
