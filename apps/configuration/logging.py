"""Structured JSON logging with mandatory secret redaction."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime

from apps.secrets.redaction import redact_text

_CONTEXT_FIELDS = (
    "event",
    "task_id",
    "source_id",
    "source_post_id",
    "x_post_id",
    "analysis_id",
    "delivery_target_id",
    "delivery_id",
    "status",
    "error_type",
)


class JsonLogFormatter(logging.Formatter):
    """Serialize a stable log envelope and redact the final JSON payload."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for field in _CONTEXT_FIELDS:
            value = getattr(record, field, None)
            if value not in (None, ""):
                payload[field] = value

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        serialized = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            default=str,
        )
        return redact_text(serialized)
