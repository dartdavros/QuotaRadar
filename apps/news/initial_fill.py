"""Explicit one-time real-channel fill; no process-start or local auto-bootstrap."""
from datetime import timedelta
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from apps.sources.models import Feed, SourcePost, SourceSubscription
from .errors import NewsPolicyError
from .models import (InitialFill, InitialFillSource, InitialFillAssessment, NewsAssessment,
                     NewsConfiguration, NewsEvent, NewsPublication)

ACTIVE_FILL = ("archive", "collecting", "assessing", "publishing")
# Seeding a new channel: its own cap, window and threshold, unrelated to the daily quota.
FILL_LIMIT = 20
FILL_WINDOW_DAYS = 4
FILL_MIN_SCORE = 50

def enabled(config):
    return (settings.QUOTARADAR_NEWS_INITIAL_FILL_ALLOWED and config.collection_enabled
            and config.analysis_enabled and config.publishing_enabled)

@transaction.atomic
def start_fill():
    if not settings.QUOTARADAR_NEWS_INITIAL_FILL_ALLOWED:
        raise NewsPolicyError("Первичное наполнение разрешается только на рабочем сервере; здесь оно выключено.")
    config = NewsConfiguration.objects.select_for_update(of=("self",)).select_related("target").get(pk=1)
    config.full_clean()
    if not enabled(config) or not config.target:
        raise NewsPolicyError("Сначала настройте канал и включите все три переключателя новостей.")
    if InitialFill.objects.filter(target=config.target).exists():
        raise NewsPolicyError("Наполнение этого канала уже запускалось; перезапуск не создаёт новый бюджет.")
    now = timezone.now()
    run = InitialFill.objects.create(target=config.target, status="archive",
        window_start=now-timedelta(days=FILL_WINDOW_DAYS), window_end=now-timedelta(seconds=15), expires_at=now+timedelta(hours=24))
    subscriptions = SourceSubscription.objects.filter(feed=Feed.NEWS, enabled=True, source__enabled=True)
    if not subscriptions.exists():
        raise NewsPolicyError("Нет включённых новостных источников.")
    InitialFillSource.objects.bulk_create([
        InitialFillSource(run=run, subscription=sub, query_terms=sub.query_terms) for sub in subscriptions])
    register_archive(run)
    return run

def register_archive(run):
    sources = run.sources.values_list("subscription__source_id", flat=True)
    posts = SourcePost.objects.filter(source_id__in=sources,
        published_at__gte=run.window_start, published_at__lte=run.window_end)
    for post in posts.iterator(chunk_size=200):
        assessment, _ = NewsAssessment.objects.get_or_create(post=post)
        InitialFillAssessment.objects.get_or_create(run=run, assessment=assessment)

def candidates(run):
    assessment_posts = run.assessments.values_list("assessment__post_id", flat=True)
    return NewsEvent.objects.filter(evidence__post_id__in=assessment_posts, score__gte=FILL_MIN_SCORE).exclude(
        event_type="incident").exclude(publications__target_id=run.target_id).distinct()

def products(run):
    """Distinct products among candidates; repeated takes on one product are one news item."""
    return {name.strip().casefold() for name in candidates(run).values_list("product", flat=True)}

def rank(run, limit):
    """One best event per product, then oldest first so the channel reads like a real timeline."""
    best = {}
    for event in candidates(run).order_by("-score", "-urgent", "-last_seen_at"):
        best.setdefault(event.product.strip().casefold(), event)
    chosen = sorted(best.values(), key=lambda event: (-event.score, event.first_seen_at))[:limit]
    return sorted(chosen, key=lambda event: event.first_seen_at)

def pending_assessments(run):
    return run.assessments.filter(assessment__status__in=("pending", "running"),
        assessment__post__source__enabled=True, assessment__post__source__subscriptions__feed=Feed.NEWS,
        assessment__post__source__subscriptions__enabled=True).exists()

@transaction.atomic
def select_initial(run_id):
    config = NewsConfiguration.objects.select_for_update(of=("self",)).select_related("target").get(pk=1)
    run = InitialFill.objects.select_for_update().get(pk=run_id)
    if not enabled(config) or config.target_id != run.target_id or run.expires_at <= timezone.now():
        return
    if run.status != "assessing" or pending_assessments(run):
        return
    remaining = FILL_LIMIT-run.publications.exclude(status="blocked").count()
    selected = 0
    for event in rank(run, max(remaining, 0)):
        # slot_date stays empty: history goes out at once and never occupies a regular publication slot.
        NewsPublication.objects.create(event=event, target_id=run.target_id, initial_fill=run, urgent=False)
        selected += 1
    run.status = "publishing" if selected or run.publications.exists() else "completed"
    if run.status == "completed":
        run.last_error = "В пределах окна и бюджета не найдено подходящих новых событий."
    run.save(update_fields=("status", "last_error"))
