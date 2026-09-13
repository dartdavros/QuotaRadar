"""The last day of failures, grouped so one flapping error does not bury the rest."""
from __future__ import annotations

from datetime import timedelta

from django.db.models import Count, Max
from django.urls import reverse

from apps.monitoring.models import MonitoringComponent, MonitoringEvent, MonitoringEventStatus
from apps.news.models import NewsPublication

from .report import ErrorRow, age, short

WINDOW = timedelta(hours=24)
LIMIT = 12


def monitoring_errors(now) -> list[ErrorRow]:
    events = MonitoringEvent.objects.filter(status=MonitoringEventStatus.ERROR, created_at__gte=now - WINDOW)
    groups = (events.values("component", "error_type").annotate(count=Count("pk"), last=Max("created_at"))
              .order_by("-last")[:LIMIT])
    changelist = reverse("admin:monitoring_monitoringevent_changelist")
    rows = []
    for group in groups:
        latest = events.filter(component=group["component"], error_type=group["error_type"]).first()
        rows.append(ErrorRow(
            when=group["last"], at=age(group["last"], now), component=MonitoringComponent(group["component"]).label,
            error_type=group["error_type"] or "—", message=short(latest.message if latest else ""),
            count=group["count"], url=f"{changelist}?component={group['component']}&status=error",
        ))
    return rows


def news_errors(now) -> list[ErrorRow]:
    publications = (NewsPublication.objects.filter(status__in=("blocked", "uncertain"), created_at__gte=now - WINDOW)
                    .exclude(last_error="").order_by("-created_at")[:LIMIT])
    changelist = reverse("admin:news_newspublication_changelist")
    return [ErrorRow(
        when=p.created_at, at=age(p.created_at, now), component="Новости", error_type=p.get_status_display(),
        message=short(p.last_error), count=1, url=f"{changelist}?status__exact={p.status}",
    ) for p in publications]


def recent_errors(now) -> list[ErrorRow]:
    return sorted(monitoring_errors(now) + news_errors(now), key=lambda row: row.when, reverse=True)[:LIMIT]
