"""Transactional persistence for successful and failed post analyses."""

from __future__ import annotations

from dataclasses import dataclass

from django.db import transaction

from apps.configuration.models import SystemConfiguration
from apps.sources.models import SourcePost, SourcePostProcessingStatus

from .llm import LlmAnalysisResponse
from .models import Analysis
from .quality import expected_product


@dataclass(frozen=True, slots=True)
class PersistedAnalysis:
    analysis: Analysis
    created: bool


def find_successful_analysis(source_post: SourcePost) -> Analysis | None:
    try:
        analysis = source_post.analysis
    except Analysis.DoesNotExist:
        return None
    return analysis if analysis.is_successful else None


@transaction.atomic
def save_successful_analysis(
    *,
    source_post_id: int,
    response: LlmAnalysisResponse,
    configuration: SystemConfiguration,
) -> PersistedAnalysis:
    source_post = (
        SourcePost.objects.select_for_update()
        .select_related("source")
        .get(pk=source_post_id)
    )
    existing = Analysis.objects.filter(source_post=source_post).first()
    if existing is not None and existing.is_successful:
        return PersistedAnalysis(analysis=existing, created=False)

    payload = response.payload
    values = {
        "is_relevant": payload.is_relevant,
        "event_type": payload.event_type or "",
        "provider": payload.provider,
        "product": payload.product,
        "title_ru": payload.title_ru or "",
        "message_ru": payload.message_ru or "",
        "model": configuration.llm_model,
        "prompt_version": configuration.active_prompt.version,
        "raw_response": response.raw_response,
        "error": "",
    }
    if existing is None:
        analysis = Analysis(source_post=source_post, **values)
        created = True
    else:
        analysis = existing
        for field, value in values.items():
            setattr(analysis, field, value)
        created = False
    analysis.full_clean()
    analysis.save()

    source_post.processing_status = (
        SourcePostProcessingStatus.ANALYZED_RELEVANT
        if payload.is_relevant
        else SourcePostProcessingStatus.ANALYZED_IRRELEVANT
    )
    source_post.processing_started_at = None
    source_post.last_error = ""
    source_post.save(
        update_fields=("processing_status", "processing_started_at", "last_error")
    )
    return PersistedAnalysis(analysis=analysis, created=created)


@transaction.atomic
def save_failed_analysis(
    *,
    source_post_id: int,
    configuration: SystemConfiguration,
    error: str,
    raw_response: object | None = None,
) -> Analysis:
    source_post = (
        SourcePost.objects.select_for_update()
        .select_related("source")
        .get(pk=source_post_id)
    )
    existing = Analysis.objects.filter(source_post=source_post).first()
    if existing is not None and existing.is_successful:
        return existing

    values = {
        "is_relevant": None,
        "event_type": "",
        "provider": source_post.source.provider,
        "product": expected_product(source_post.source.provider),
        "title_ru": "",
        "message_ru": "",
        "model": configuration.llm_model or "unconfigured",
        "prompt_version": configuration.active_prompt.version,
        "raw_response": raw_response,
        "error": error,
    }
    if existing is None:
        analysis = Analysis(source_post=source_post, **values)
    else:
        analysis = existing
        for field, value in values.items():
            setattr(analysis, field, value)
    analysis.full_clean()
    analysis.save()

    source_post.processing_status = SourcePostProcessingStatus.FAILED
    source_post.processing_started_at = None
    source_post.last_error = error
    source_post.save(
        update_fields=("processing_status", "processing_started_at", "last_error")
    )
    return analysis
