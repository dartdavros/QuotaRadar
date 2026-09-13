"""Plain data for the admin health panel: one Check per subsystem, one verdict overall."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from zoneinfo import ZoneInfo

from django.urls import reverse

# Ordered from healthy to broken; OFF means "switched off by the operator", not a fault.
OK, OFF, WARN, ERROR = "ok", "off", "warn", "error"
SEVERITY = {OK: 0, OFF: 1, WARN: 2, ERROR: 3}
FAULTS = (WARN, ERROR)
LABELS = {OK: "Работает", OFF: "Выключено", WARN: "Внимание", ERROR: "Ошибка"}


@dataclass
class Link:
    label: str
    url: str


@dataclass
class Check:
    title: str
    group: str = ""
    level: str = OK
    summary: str = ""            # One line: what is wrong, or what is fine.
    details: list[str] = field(default_factory=list)
    last_success: str = ""       # Humanized, already formatted.
    last_error_at: str = ""
    last_error: str = ""
    links: list[Link] = field(default_factory=list)

    @property
    def label(self) -> str:
        return LABELS[self.level]

    def fail(self, level: str, summary: str) -> None:
        """Escalate to ``level`` unless already worse; keep the first summary that was set."""
        if SEVERITY[level] > SEVERITY[self.level]:
            self.level, self.summary = level, summary
        elif SEVERITY[level] == SEVERITY[self.level] and not self.summary:
            self.summary = summary


@dataclass
class ErrorRow:
    when: datetime
    at: str
    component: str
    error_type: str
    message: str
    count: int
    url: str


@dataclass
class Dashboard:
    generated_at: str
    level: str
    headline: str
    checks: list[Check]
    errors: list[ErrorRow]
    failure: str = ""            # Set when the panel itself could not be built.

    @property
    def label(self) -> str:
        return LABELS[self.level]

    @property
    def groups(self) -> list[tuple[str, list[Check]]]:
        """Checks in display order, bucketed by their group, first appearance wins."""
        buckets: dict[str, list[Check]] = {}
        for check in self.checks:
            buckets.setdefault(check.group, []).append(check)
        return list(buckets.items())

    @property
    def problems(self) -> int:
        return sum(1 for c in self.checks if c.level in FAULTS)


def worst(checks: list[Check]) -> str:
    """Overall verdict; switched-off subsystems are not faults."""
    return max((c.level for c in checks if c.level in FAULTS), key=lambda level: SEVERITY[level], default=OK)


def headline_for(checks: list[Check]) -> str:
    errors = sum(1 for c in checks if c.level == ERROR)
    warnings = sum(1 for c in checks if c.level == WARN)
    if errors:
        return f"НЕ РАБОТАЕТ: {errors} компонент(ов) с ошибкой" + (f", {warnings} с предупреждением" if warnings else "")
    if warnings:
        return f"РАБОТАЕТ С ЗАМЕЧАНИЯМИ: {warnings} предупреждение(й)"
    return "ВСЁ РАБОТАЕТ"


def age(moment: datetime | None, now: datetime) -> str:
    if moment is None:
        return "никогда"
    seconds = int((now - moment).total_seconds())
    if seconds < 0:
        return "в будущем"
    if seconds < 60:
        return f"{seconds} с назад"
    if seconds < 3600:
        return f"{seconds // 60} мин назад"
    if seconds < 86400:
        return f"{seconds // 3600} ч {seconds % 3600 // 60} мин назад"
    return f"{seconds // 86400} д назад"


def clock(moment: datetime, tz: str) -> str:
    try:
        local = moment.astimezone(ZoneInfo(tz))
    except Exception:  # A broken timezone string must not break the panel.
        local = moment
    return local.strftime("%d.%m.%Y %H:%M:%S")


def short(text: str, limit: int = 220) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def admin_link(label: str, view: str, query: str = "", args: tuple = ()) -> Link:
    url = reverse(f"admin:{view}", args=args)
    return Link(label, f"{url}?{query}" if query else url)


def minutes(seconds: int | float) -> str:
    return f"{int(seconds // 60)} мин"
