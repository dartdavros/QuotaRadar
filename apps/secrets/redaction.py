"""Logging helpers that remove registered credentials and proxy userinfo."""

from __future__ import annotations

import logging
import re
import threading
from collections.abc import Iterable

_PROXY_USERINFO_PATTERN = re.compile(
    r"(?P<scheme>https?://)(?P<userinfo>[^\s/@:]+(?::[^\s/@]*)?@)",
    flags=re.IGNORECASE,
)
_BEARER_PATTERN = re.compile(r"(?i)(authorization\s*:\s*bearer\s+)[^\s,;]+")
_LOCK = threading.RLock()
_SENSITIVE_VALUES: set[str] = set()


def register_sensitive_value(value: str | None) -> None:
    if not value:
        return
    with _LOCK:
        _SENSITIVE_VALUES.add(value)


def register_sensitive_values(values: Iterable[str]) -> None:
    for value in values:
        register_sensitive_value(value)


def redact_text(value: str) -> str:
    with _LOCK:
        sensitive_values = sorted(_SENSITIVE_VALUES, key=len, reverse=True)
    redacted = value
    for sensitive in sensitive_values:
        redacted = redacted.replace(sensitive, "***")
    redacted = _PROXY_USERINFO_PATTERN.sub(r"\g<scheme>***:***@", redacted)
    return _BEARER_PATTERN.sub(r"\1***", redacted)


class SafeFormatter(logging.Formatter):
    """Format first, then redact secrets from messages and traceback text."""

    def format(self, record: logging.LogRecord) -> str:
        return redact_text(super().format(record))


def clear_registered_values() -> None:
    """Clear process-local registrations; intended for isolated test execution."""

    with _LOCK:
        _SENSITIVE_VALUES.clear()
