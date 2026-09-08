"""Turn independent assessments into deduplicated news events."""
from datetime import timedelta
from hashlib import sha256
import re

from django.db import transaction
from django.utils import timezone

from .llm import ask
from .errors import NewsPolicyError
from .models import NewsAssessment, NewsEvent, NewsEventEvidence
from .quality import validate_assessment
from .schemas import AssessmentPayload


def candidates_for(post):
    return list(NewsEvent.objects.filter(
        last_seen_at__gte=post.published_at-timedelta(days=7),
    ).order_by("-last_seen_at").values("id", "product", "version", "event_type", "facts")[:20])


def assess(assessment_id, config):
    now = timezone.now()
    with transaction.atomic():
        assessment = NewsAssessment.objects.select_for_update().select_related("post__source").get(pk=assessment_id)
        if assessment.status in {"done", "blocked"}:
            return
        if assessment.lease_until and assessment.lease_until > now:
            return
        if assessment.next_attempt_at and assessment.next_attempt_at > now:
            return
        if assessment.attempts >= 3:
            assessment.status, assessment.last_error = "blocked", "Попытки анализа исчерпаны."
            assessment.save()
            return
        assessment.status = "running"
        assessment.attempts += 1
        assessment.lease_until = now + timedelta(minutes=5)
        assessment.save()
    try:
        payload, model, usage = ask(config, prompt=config.assessment_prompt, schema=AssessmentPayload,
            data={"source": assessment.post.source.username, "post": assessment.post.normalized_text,
                  "date": assessment.post.published_at.isoformat(), "existing_events": candidates_for(assessment.post)})
        validate_assessment(payload, assessment.post)
        with transaction.atomic():
            current = NewsAssessment.objects.select_for_update().get(pk=assessment.pk)
            if current.status == "done" or current.attempts != assessment.attempts:
                return
            current.result = payload.model_dump()
            current.model, current.usage = model, usage
            current.prompt_version = config.assessment_prompt.version
            current.status, current.lease_until, current.last_error = "done", None, payload.reason
            current.save()
            if payload.relevant:
                save_event(current.post, payload, config)
    except Exception as exc:
        NewsAssessment.objects.filter(pk=assessment_id, attempts=assessment.attempts, status="running").update(
            status="blocked" if assessment.attempts >= 3 else "pending",
            lease_until=None, next_attempt_at=now+timedelta(minutes=5),
            last_error=str(exc) if isinstance(exc, NewsPolicyError) else f"Анализ не завершён: {type(exc).__name__}.",
        )


def save_event(post, payload, config):
    facts = [fact.model_dump() for fact in payload.facts]
    key = "" if payload.event_type in {"model_release", "tool_release"} and payload.version else payload.event_key
    identity = "|".join((payload.product, payload.version, payload.event_type, key))
    identity = re.sub(r"\s+", " ", identity).strip().casefold()
    fingerprint = sha256(identity.encode()).hexdigest()
    # Serialize grouping decisions, including semantically matched events.
    type(config).objects.select_for_update().get(pk=config.pk)
    event = None
    if payload.related_event_id:
        allowed = {candidate["id"] for candidate in candidates_for(post)}
        if payload.related_event_id not in allowed:
            raise NewsPolicyError("Событие для объединения не было предложено редактору.")
        event = NewsEvent.objects.select_for_update().filter(
            pk=payload.related_event_id, product__iexact=payload.product,
            version__iexact=payload.version, event_type=payload.event_type,
        ).first()
        if event is None:
            raise NewsPolicyError("События относятся к разным продуктам или версиям.")
    if event is None:
        event, _ = NewsEvent.objects.get_or_create(fingerprint=fingerprint, defaults={
            "product": payload.product, "version": payload.version, "event_type": payload.event_type,
            "score": payload.score, "urgent": payload.urgent, "facts": facts,
            "first_seen_at": post.published_at, "last_seen_at": post.published_at,
            "expires_at": post.published_at+timedelta(hours=config.expiry_hours),
        })
    NewsEventEvidence.objects.get_or_create(event=event, post=post, defaults={"facts": facts})
    existing = {fact["text"] for fact in event.facts}
    event.facts += [fact for fact in facts if fact["text"] not in existing]
    event.score = max(event.score, payload.score)
    event.urgent = event.urgent or payload.urgent
    event.last_seen_at = max(event.last_seen_at, post.published_at)
    event.save()
