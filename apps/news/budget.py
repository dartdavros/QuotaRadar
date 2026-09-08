"""Atomically reserve both weekly spending and the one-time $2 historical fill."""
from datetime import timedelta, timezone as dt_timezone
from decimal import Decimal
from django.db import transaction
from django.utils import timezone
from .models import InitialFill, XApiUsage, XBudgetPeriod

FILL_LIMIT = Decimal("2.000")

class BudgetExhausted(RuntimeError):
    pass

@transaction.atomic
def reserve(source, config, *, maximum, priority, operation="recent_search", initial_fill_id=None):
    run = None
    if initial_fill_id is not None:
        run = InitialFill.objects.select_for_update().get(pk=initial_fill_id)
        if run.status != "collecting" or run.expires_at <= timezone.now() or run.committed + maximum > FILL_LIMIT:
            raise BudgetExhausted("Предел первичного наполнения X исчерпан.")
    current = timezone.now().astimezone(dt_timezone.utc).date()
    week = current - timedelta(days=current.weekday())
    XBudgetPeriod.objects.get_or_create(week=week, defaults={"limit": config.weekly_x_limit})
    period = XBudgetPeriod.objects.select_for_update().get(week=week)
    ceiling = min(period.limit, config.weekly_x_limit, Decimal("3"))
    if not priority and run is None:
        ceiling *= Decimal("0.8")
    if maximum <= 0 or period.committed + maximum > ceiling:
        raise BudgetExhausted("Недельный бюджет новых X-запросов исчерпан.")
    period.committed += maximum
    period.save(update_fields=("committed",))
    if run:
        run.committed += maximum
        run.save(update_fields=("committed",))
    return XApiUsage.objects.create(period=period, source=source, operation=operation,
                                   reserved=maximum, initial_fill=run)

@transaction.atomic
def settle(usage_id, *, resources=None):
    usage = XApiUsage.objects.select_for_update().get(pk=usage_id)
    if usage.status != "reserved":
        return
    if resources is None:
        usage.status = "uncertain"
        usage.save(update_fields=("status",))
        return
    actual = Decimal(resources) * Decimal("0.005")
    if actual < 0 or actual > usage.reserved:
        raise ValueError("Ответ X вышел за зарезервированный размер страницы.")
    if usage.initial_fill_id:
        run = InitialFill.objects.select_for_update().get(pk=usage.initial_fill_id)
        run.committed += actual - usage.reserved
        run.save(update_fields=("committed",))
    period = XBudgetPeriod.objects.select_for_update().get(pk=usage.period_id)
    period.committed += actual - usage.reserved
    period.save(update_fields=("committed",))
    usage.charged_estimate, usage.resources, usage.status = actual, resources, "counted"
    usage.save(update_fields=("charged_estimate", "resources", "status"))
