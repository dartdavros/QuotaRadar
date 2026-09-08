"""Prepare, fact-check and freeze exactly one Telegram request."""
from datetime import timedelta
from django.db import transaction
from django.utils import timezone
from .llm import ask
from .errors import NewsPolicyError
from .media import preserve
from .models import NewsPublication
from .quality import render
from .payload import publication_hash, publication_expired, publication_allowed
from .schemas import WritingPayload, VerificationPayload, HistoricalVerificationPayload

def prepare(publication_id, config):
    now = timezone.now()
    with transaction.atomic():
        publication = NewsPublication.objects.select_for_update().select_related("event").get(pk=publication_id)
        if publication.status != "preparing" or not publication_allowed(publication, config):
            return
        if publication.lease_until and publication.lease_until > now:
            return
        if publication.next_attempt_at and publication.next_attempt_at > now:
            return
        if publication.attempts >= 3:
            publication.status, publication.last_error = "blocked", "Попытки подготовки исчерпаны."
            publication.save()
            return
        publication.attempts += 1
        attempt = publication.attempts
        publication.lease_until = now + timedelta(minutes=30)
        publication.save()
    try:
        evidence = list(publication.event.evidence.select_related("post__source").order_by("pk"))
        posts = [item.post for item in evidence[:3]]
        if not posts or publication_expired(publication, timezone.now()):
            raise NewsPolicyError("Нет актуального первоисточника.")
        # Only facts supported by the selected, linked originals reach the writer.
        facts = [fact for item in evidence[:3] for fact in item.facts]
        sources = [{"id": post.pk, "text": post.normalized_text, "date": post.published_at.isoformat()}
                   for post in posts]
        writing, model, writing_usage = ask(config, prompt=config.writing_prompt, schema=WritingPayload,
                                           data={"facts": facts, "sources": sources, "publication_time": now.isoformat(),
                                                 "historical": bool(publication.initial_fill_id)})
        verification, _, verification_usage = ask(config, prompt=config.verification_prompt,
            schema=HistoricalVerificationPayload if publication.initial_fill_id else VerificationPayload, data={"publication": writing.model_dump(), "sources": sources,
                "publication_time": now.isoformat(), "historical": bool(publication.initial_fill_id)})
        if not verification.supported or (publication.initial_fill_id and not verification.still_relevant):
            raise NewsPolicyError("Проверка фактов отклонила текст.")
        rendered = render(writing, posts)
        preserve(publication, posts)
        payload_hash = publication_hash(publication, rendered)
        NewsPublication.objects.filter(pk=publication_id, status="preparing", attempts=attempt).update(
            status="ready", title=writing.title, text=writing.text, rendered=rendered,
            source_ids=[post.pk for post in posts], model=model, payload_hash=payload_hash,
            prompt_versions={"writing": config.writing_prompt.version, "verification": config.verification_prompt.version},
            usage={"writing": writing_usage, "verification": verification_usage},
            lease_until=None, next_attempt_at=None, last_error="",
        )
    except Exception as exc:
        NewsPublication.objects.filter(pk=publication_id, status="preparing", attempts=attempt).update(
            status="blocked" if attempt >= 3 else "preparing", lease_until=None,
            next_attempt_at=now+timedelta(minutes=5),
            last_error=str(exc) if isinstance(exc, NewsPolicyError) else f"Подготовка не завершена: {type(exc).__name__}.",
        )
