"""Celery tasks required by the stage-one infrastructure checks."""

from __future__ import annotations

from celery import shared_task


@shared_task(name="monitoring.healthcheck")
def healthcheck() -> dict[str, str]:
    """Return a deterministic response proving that the worker accepts tasks."""
    return {"status": "ok", "service": "worker"}
