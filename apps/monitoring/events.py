"""Best-effort persistence of significant operational events."""

from __future__ import annotations

import logging

from apps.secrets.redaction import redact_text
from apps.sources.models import Source

from .models import MonitoringEvent

logger = logging.getLogger(__name__)


def record_monitoring_event(
    *,
    component: str,
    status: str,
    message: str,
    source: Source | None = None,
    error_type: str = "",
    task_id: str = "",
) -> None:
    """Persist a redacted event without interrupting the monitored workflow."""

    try:
        MonitoringEvent.objects.create(
            component=component,
            status=status,
            source_id=source.pk if source is not None else None,
            message=redact_text(message),
            error_type=error_type,
            task_id=task_id,
        )
    except Exception:
        logger.exception(
            "Monitoring event could not be persisted.",
            extra={
                "event": "monitoring.event_persist_failed",
                "source_id": source.pk if source is not None else None,
                "status": "failed",
            },
        )
