"""Serialize publication reservations and enforce a strict daily channel cap."""
from zoneinfo import ZoneInfo
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from .models import NewsConfiguration, NewsDailyQuota, NewsEvent, NewsPublication, InitialFill
from .payload import MAX_EVENT_AGE

ACTIVE = ("preparing", "ready", "sending", "sent", "uncertain")

def local_day(config, now=None):
    return (now or timezone.now()).astimezone(ZoneInfo(config.timezone))

def reserve_day(publication, config, now=None):
    """Called inside an atomic block; uncertain outcomes consume their slot."""
    if publication.initial_fill_id:
        return True  # The one-time fill keeps its own cap and never touches the regular daily quota.
    local = local_day(config, now)
    quota, _ = NewsDailyQuota.objects.get_or_create(target_id=publication.target_id, date=local.date())
    NewsDailyQuota.objects.select_for_update().get(pk=quota.pk)
    used = NewsPublication.objects.filter(
        target_id=publication.target_id, slot_date=local.date(), status__in=ACTIVE,
    ).exclude(pk=publication.pk).count()
    if used >= min(config.daily_limit, 3):
        return False
    publication.slot_date = local.date()
    return True

@transaction.atomic
def select_publication():
    config = NewsConfiguration.objects.select_for_update(of=("self",)).select_related("target").get(pk=1)
    if not config.publishing_enabled or not config.target or not config.target.enabled:
        return None
    if config.target.feed != "news" or config.target.target_type != "channel":
        return None
    now = timezone.now()
    local = local_day(config, now)
    # Never emit a backlog of missed regular windows in one burst.
    windows = [w for w in config.windows if 0 <= local.hour*60+local.minute-w < 30]
    minute = max(windows) if windows else None
    occupied = minute is not None and NewsPublication.objects.filter(
        target=config.target, slot_date=local.date(), slot_minute=minute, status__in=ACTIVE,
    ).exists()
    events = NewsEvent.objects.filter(expires_at__gt=now, first_seen_at__gt=now-MAX_EVENT_AGE, score__gte=config.min_score)
    events = events.exclude(publications__target=config.target)
    if config.activated_at:
        events = events.filter(first_seen_at__gte=config.activated_at)
    fill = InitialFill.objects.filter(target=config.target,
        status__in=("archive", "collecting", "assessing", "publishing")).first()
    if fill:
        events = events.filter(urgent=True, first_seen_at__gt=fill.window_end)
    if minute is None or occupied:
        events = events.filter(urgent=True)
    event = events.order_by("-urgent", "-score", "-last_seen_at").first()
    if not event:
        return None
    publication = NewsPublication(event=event, target=config.target, urgent=event.urgent,
                                  slot_minute=None if event.urgent else minute)
    if not reserve_day(publication, config, now):
        return None
    publication.save()
    return publication.pk

def due(queryset):
    return queryset.filter(Q(next_attempt_at__isnull=True) | Q(next_attempt_at__lte=timezone.now()))
