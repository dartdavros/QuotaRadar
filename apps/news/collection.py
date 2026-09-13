"""Persist one page at a time; a budget pause never advances past unseen posts."""
from datetime import timedelta
from hashlib import sha256

from django.db import transaction
from django.utils import timezone

from apps.configuration.models import SystemConfiguration
from apps.monitoring.locks import source_poll_lock
from apps.monitoring.services import prepare_source_posts, persist_source_posts
from apps.monitoring.x_api import XApiRateLimitError, XApiResponseError
from apps.sources.models import Feed, SourcePost, SourceSubscription
from .budget import BUDGET_PAUSE, BudgetExhausted
from .models import CollectionCheckpoint, NewsAssessment
from .x_client import build_query, fetch_page


def register_posts(config):
    if not config.activated_at:
        return 0
    sources = SourceSubscription.objects.filter(feed=Feed.NEWS, enabled=True, source__enabled=True)
    posts = SourcePost.objects.filter(
        source_id__in=sources.values("source_id"), published_at__gte=config.activated_at,
        news_assessment__isnull=True,
    ).order_by("pk")[:200]
    rows = [NewsAssessment(post=post) for post in posts]
    NewsAssessment.objects.bulk_create(rows, ignore_conflicts=True)
    return len(rows)


def collect_source(subscription, config):
    source = subscription.source
    quota_running = SystemConfiguration.load().monitoring_enabled and SourceSubscription.objects.filter(
        source=source, feed=Feed.QUOTA, enabled=True,
    ).exists()
    if quota_running:
        return "shared_quota_collector"
    with source_poll_lock(source.pk) as acquired:
        if not acquired:
            return "locked"
        checkpoint, _ = CollectionCheckpoint.objects.get_or_create(source=source)
        now = timezone.now()
        if checkpoint.next_attempt_at and checkpoint.next_attempt_at > now:
            return "waiting"
        query_hash = sha256(build_query(subscription).encode()).hexdigest()
        if checkpoint.query_hash and checkpoint.query_hash != query_hash:
            checkpoint.window_start = None
            checkpoint.window_end = None
            checkpoint.next_token = ""
            checkpoint.completed_until = None
            checkpoint.last_error = "Фильтр изменён; покрытие прежнего фильтра не переиспользуется."
        checkpoint.query_hash = query_hash
        if checkpoint.window_start is None:
            start = checkpoint.completed_until or config.activated_at
            floor = now - timedelta(days=6, hours=23)
            if start < floor:
                checkpoint.last_error = "Пропуск: часть истории старше окна recent search."
                start = floor
            checkpoint.window_start = start
            checkpoint.window_end = now - timedelta(seconds=15)
        if checkpoint.window_start >= checkpoint.window_end:
            return "empty_window"
        checkpoint.save()
        try:
            page = fetch_page(subscription, checkpoint, config)
            if page.errors:
                raise XApiResponseError("X вернул неполную страницу; курсор не продвинут.")
            prepared, _, _ = prepare_source_posts(source, [page])
            token = page.meta.get("next_token") or ""
            if not isinstance(token, str) or (token and token == checkpoint.next_token):
                raise XApiResponseError("Неверный курсор продолжения X.")
            with transaction.atomic():
                persist_source_posts(source=source, prepared=prepared)
                checkpoint.next_token = token
                if not token:
                    checkpoint.completed_until = checkpoint.window_end
                    checkpoint.window_start = None
                    checkpoint.window_end = None
                checkpoint.next_attempt_at = now + timedelta(seconds=10 if token else 120)
                checkpoint.last_error = ""  # A saved page supersedes whatever stopped the previous attempt.
                checkpoint.save()
            return "page_saved"
        except BudgetExhausted:
            checkpoint.next_attempt_at = now + timedelta(minutes=30)
            checkpoint.last_error = BUDGET_PAUSE
        except XApiRateLimitError as exc:
            checkpoint.next_attempt_at = now + timedelta(seconds=exc.retry_after_seconds())
            checkpoint.last_error = "X ограничил частоту запросов."
        except Exception as exc:
            checkpoint.next_attempt_at = now + timedelta(minutes=5)
            checkpoint.last_error = f"Сбор приостановлен: {type(exc).__name__}."
            if isinstance(exc, XApiResponseError) and checkpoint.next_token:
                # Re-read the same bounded interval, with archive deduplication.
                checkpoint.next_token = ""
        checkpoint.save()
        return "paused"
