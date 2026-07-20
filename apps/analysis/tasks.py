"""Celery task for idempotent LLM interpretation of source posts."""

from __future__ import annotations

import logging

from celery import Task, shared_task

from apps.configuration.models import SystemConfiguration
from apps.sources.models import SourcePost, SourcePostProcessingStatus

from .llm import (
    LlmAuthenticationError,
    LlmConfigurationError,
    LlmForbiddenError,
    LlmResponseError,
    LlmStructuredOutputError,
    LlmTemporaryError,
    create_llm_client,
)
from .models import Analysis
from .prompts import PromptConfigurationError, render_prompt
from .quality import AnalysisQualityError, validate_payload_for_post
from .services import (
    find_successful_analysis,
    save_failed_analysis,
    save_successful_analysis,
)

logger = logging.getLogger(__name__)
_BASE_RETRY_SECONDS = 30
_MAX_RETRY_SECONDS = 900


@shared_task(bind=True, name="analysis.analyze_post")
def analyze_post(self: Task, source_post_id: int) -> dict[str, int | str | bool]:
    """Analyze one post once, retrying only temporary or invalid LLM responses."""

    try:
        source_post = SourcePost.objects.select_related("source").get(pk=source_post_id)
    except SourcePost.DoesNotExist:
        return {"status": "missing", "source_post_id": source_post_id}

    completed = find_successful_analysis(source_post)
    if completed is not None:
        return {
            "status": "already_analyzed",
            "source_post_id": source_post_id,
            "analysis_id": completed.pk,
            "is_relevant": bool(completed.is_relevant),
        }

    SourcePost.objects.filter(pk=source_post_id).update(
        processing_status=SourcePostProcessingStatus.QUEUED,
        last_error="",
    )
    configuration = SystemConfiguration.load()
    raw_response: object | None = None
    try:
        prompt = render_prompt(
            source_post=source_post,
            configuration=configuration,
        )
        with create_llm_client(configuration=configuration) as client:
            response = client.analyze(
                system_prompt=prompt.system_prompt,
                user_prompt=prompt.user_prompt,
            )
        raw_response = response.raw_response
        validate_payload_for_post(payload=response.payload, source_post=source_post)
    except LlmStructuredOutputError as exc:
        raw_response = exc.raw_response
        return _retry_or_fail(
            task=self,
            source_post_id=source_post_id,
            configuration=configuration,
            exc=exc,
            raw_response=raw_response,
        )
    except (LlmTemporaryError, AnalysisQualityError) as exc:
        return _retry_or_fail(
            task=self,
            source_post_id=source_post_id,
            configuration=configuration,
            exc=exc,
            raw_response=raw_response,
        )
    except _PERMANENT_ANALYSIS_ERRORS as exc:
        analysis = save_failed_analysis(
            source_post_id=source_post_id,
            configuration=configuration,
            error=str(exc),
            raw_response=raw_response,
        )
        logger.error(
            "Post analysis failed for source_post_id=%s: %s", source_post_id, exc
        )
        return _failure_result(source_post_id=source_post_id, analysis=analysis)

    persisted = save_successful_analysis(
        source_post_id=source_post_id,
        response=response,
        configuration=configuration,
    )
    return {
        "status": "ok" if persisted.created else "already_analyzed",
        "source_post_id": source_post_id,
        "analysis_id": persisted.analysis.pk,
        "is_relevant": bool(persisted.analysis.is_relevant),
    }


_PERMANENT_ANALYSIS_ERRORS = (
    LlmConfigurationError,
    LlmAuthenticationError,
    LlmForbiddenError,
    LlmResponseError,
    PromptConfigurationError,
)


def _retry_or_fail(
    *,
    task: Task,
    source_post_id: int,
    configuration: SystemConfiguration,
    exc: Exception,
    raw_response: object | None,
) -> dict[str, int | str]:
    retries = getattr(task.request, "retries", 0)
    if retries < configuration.retry_count:
        countdown = min(_BASE_RETRY_SECONDS * (2**retries), _MAX_RETRY_SECONDS)
        logger.warning(
            "Temporary or invalid LLM response; retry scheduled for source_post_id=%s: %s",
            source_post_id,
            exc,
        )
        raise task.retry(
            exc=exc,
            countdown=countdown,
            max_retries=configuration.retry_count,
        )

    analysis = save_failed_analysis(
        source_post_id=source_post_id,
        configuration=configuration,
        error=str(exc),
        raw_response=raw_response,
    )
    return _failure_result(source_post_id=source_post_id, analysis=analysis)


def _failure_result(
    *, source_post_id: int, analysis: Analysis
) -> dict[str, int | str | bool]:
    if analysis.is_successful:
        return {
            "status": "already_analyzed",
            "source_post_id": source_post_id,
            "analysis_id": analysis.pk,
            "is_relevant": bool(analysis.is_relevant),
        }
    return {
        "status": "failed",
        "source_post_id": source_post_id,
        "analysis_id": analysis.pk,
    }
