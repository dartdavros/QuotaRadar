"""Round-robin bounded history reads, then ranking of the whole collected batch."""
from datetime import timedelta
from types import SimpleNamespace
from django.db import transaction
from django.db.models import F
from django.utils import timezone
from apps.monitoring.locks import source_poll_lock
from apps.monitoring.services import prepare_source_posts, persist_source_posts
from apps.monitoring.x_api import XApiResponseError, XApiRateLimitError
from .scheduling import due
from .budget import BudgetExhausted
from .initial_fill import enabled, register_archive, candidates, pending_assessments, select_initial
from .models import InitialFill, InitialFillSource
from .x_client import fetch_page

def advance(run_id, config):
    if not enabled(config):
        return
    now = timezone.now()
    with transaction.atomic():
        run = InitialFill.objects.select_for_update().get(pk=run_id)
        if run.status in ("completed", "blocked") or config.target_id != run.target_id:
            return
        if run.lease_until and run.lease_until > now:
            return
        if run.expires_at <= now:
            run.status, run.last_error = "blocked", "Время первого наполнения истекло; новый платный запуск не создаётся."
            run.save()
            return
        run.lease_until = now+timedelta(minutes=2)
        run.save(update_fields=("lease_until",))
    try:
        register_archive(run)
        if run.status == "archive":
            if not pending_assessments(run):
                run.status = "assessing" if candidates(run, config).count() >= 3 else "collecting"
                run.save(update_fields=("status",))
        elif run.status == "collecting":
            read_page(run, config)
        elif run.status == "assessing":
            select_initial(run.pk)
        elif run.status == "publishing":
            if not run.publications.exclude(status__in=("sent", "blocked")).exists():
                run.status = "completed"
                run.save(update_fields=("status",))
    finally:
        InitialFill.objects.filter(pk=run_id, lease_until=run.lease_until).update(lease_until=None)

def read_page(run, config):
    row = due(run.sources.filter(done=False)).select_related("subscription__source").order_by(
        F("checked_at").asc(nulls_first=True), "pk").first()
    if row is None:
        if not run.sources.filter(done=False).exists():
            InitialFill.objects.filter(pk=run.pk).update(status="assessing")
        return
    subscription = row.subscription
    if not subscription.enabled or not subscription.source.enabled:
        row.done, row.last_error = True, "Источник отключён."
        row.save()
        return
    subscription.query_terms = row.query_terms  # Fixed filter for the whole run.
    with source_poll_lock(subscription.source_id) as acquired:
        if not acquired:
            return
        checkpoint = SimpleNamespace(window_start=run.window_start, window_end=run.window_end, next_token=row.next_token)
        row.checked_at = timezone.now()
        try:
            page = fetch_page(subscription, checkpoint, config, initial_fill_id=run.pk)
            if page.errors:
                raise XApiResponseError("Неполная страница истории.")
            prepared, _, _ = prepare_source_posts(subscription.source, [page])
            token = page.meta.get("next_token") or ""
            if not isinstance(token, str) or token and token == row.next_token:
                raise XApiResponseError("Неверный курсор истории.")
            with transaction.atomic():
                persist_source_posts(source=subscription.source, prepared=prepared)
                row.next_token, row.done, row.attempts = token, not bool(token), 0
                row.save()
            register_archive(run)
        except BudgetExhausted:
            InitialFill.objects.filter(pk=run.pk).update(status="assessing",
                last_error="Достигнут предел X: используем уже полученные посты.")
        except Exception as exc:
            row.attempts += 1
            delay = exc.retry_after_seconds() if isinstance(exc, XApiRateLimitError) else 300
            row.next_attempt_at = timezone.now()+timedelta(seconds=delay)
            row.done = row.attempts >= 3
            row.last_error = f"История источника: {type(exc).__name__}."
            if isinstance(exc, XApiResponseError):
                row.next_token = ""
            row.save()
