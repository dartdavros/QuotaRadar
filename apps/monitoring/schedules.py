"""Celery Beat schedule driven by the database-backed polling interval."""

from __future__ import annotations

from datetime import timedelta

from celery.schedules import schedule

_DEFAULT_POLL_INTERVAL_SECONDS = 300


class DatabasePollingSchedule(schedule):
    """Reload the configured interval whenever Celery Beat evaluates the task."""

    def __init__(self, fallback_seconds: int = _DEFAULT_POLL_INTERVAL_SECONDS) -> None:
        self.fallback_seconds = fallback_seconds
        super().__init__(run_every=timedelta(seconds=fallback_seconds))

    def is_due(self, last_run_at):  # type: ignore[no-untyped-def]
        self.run_every = timedelta(seconds=self._load_interval_seconds())
        return super().is_due(last_run_at)

    def _load_interval_seconds(self) -> int:
        try:
            from django.db import DatabaseError

            from apps.configuration.models import SystemConfiguration

            return max(SystemConfiguration.load().poll_interval_seconds, 1)
        except (DatabaseError, SystemConfiguration.DoesNotExist):
            return self.fallback_seconds

    def __reduce__(self):
        return (type(self), (self.fallback_seconds,))
