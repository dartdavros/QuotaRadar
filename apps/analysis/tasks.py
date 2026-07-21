"""Celery task for idempotent LLM interpretation of source posts."""

from __future__ import annotations

import logging

from celery import Task, shared_task
from django.utils import timezone

from apps.configuration.models import SystemConfiguration
from apps.monitoring.events import record_monitoring_event
from apps.monitoring.models import MonitoringComponent, MonitoringEventStatus
from apps.sources.models import SourcePost, SourcePostProcessingStatus
from apps.telegram.services import queue_analysis_deliveries

from .llm import (
    LlmAuthenticationError,
    LlmConfigurationError,
    LlmForbiddenError,
    LlmResponseError,
    LlmStructuredOutputError,
    LlmTemporaryError,
    create_llm_client,
)
from .locks import source_post_analysis_lock
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

    context = {
        "event": "analysis.started",
        "task_id": _task_id(self),
        "source_id": source_post.source_id,
        "x_post_id": source_post.external_id,
    }
    logger.info("Post analysis started.", extra=context)

    with source_post_analysis_lock(source_post_id) as acquired:
        if not acquired:
            logger.info(
                "Post analysis skipped because the lock is held.",
                extra={**context, "event": "analysis.locked", "status": "locked"},
            )
            return {"status": "locked", "source_post_id": source_post_id}
        return _analyze_locked(task=self, source_post=source_post, context=context)


def _analyze_locked(
    *,
    task: Task,
    source_post: SourcePost,
    context: dict[str, object],
) -> dict[str, int | str | bool]:
    completed = find_successful_analysis(source_post)
    if completed is not None:
        queued_deliveries = 0
        if completed.is_relevant is True:
            queued = queue_analysis_deliveries(completed.pk)
            queued_deliveries = len(queued.delivery_ids)
        result = {
            "status": "already_analyzed",
            "source_post_id": source_post.pk,
            "analysis_id": completed.pk,
            "is_relevant": bool(completed.is_relevant),
            "queued_deliveries": queued_deliveries,
        }
        logger.info(
            "Post was already analyzed.",
            extra={
                **context,
                "event": "analysis.already_completed",
                "analysis_id": completed.pk,
                "status": "already_analyzed",
            },
        )
        return result

    SourcePost.objects.filter(pk=source_post.pk).update(
        processing_status=SourcePostProcessingStatus.QUEUED,
        processing_started_at=timezone.now(),
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
            task=task,
            source_post=source_post,
            configuration=configuration,
            exc=exc,
            raw_response=raw_response,
            context=context,
        )
    except (LlmTemporaryError, AnalysisQualityError) as exc:
        return _retry_or_fail(
            task=task,
            source_post=source_post,
            configuration=configuration,
            exc=exc,
            raw_response=raw_response,
            context=context,
        )
    except _PERMANENT_ANALYSIS_ERRORS as exc:
        analysis = save_failed_analysis(
            source_post_id=source_post.pk,
            configuration=configuration,
            error=str(exc),
            raw_response=raw_response,
        )
        logger.error(
            "Post analysis failed permanently.",
            extra={
                **context,
                "event": "analysis.failed",
                "analysis_id": analysis.pk,
                "status": "failed",
                "error_type": type(exc).__name__,
            },
        )
        record_monitoring_event(
            component=MonitoringComponent.AI,
            status=MonitoringEventStatus.ERROR,
            source=source_post.source,
            message=f"Ошибка анализа поста {source_post.external_id}: {exc}",
            error_type=type(exc).__name__,
            task_id=_task_id(task),
        )
        return _failure_result(source_post_id=source_post.pk, analysis=analysis)

    persisted = save_successful_analysis(
        source_post_id=source_post.pk,
        response=response,
        configuration=configuration,
    )
    queued_deliveries = 0
    if persisted.analysis.is_relevant is True:
        queued = queue_analysis_deliveries(persisted.analysis.pk)
        queued_deliveries = len(queued.delivery_ids)
    status = "ok" if persisted.created else "already_analyzed"
    logger.info(
        "Post analysis completed.",
        extra={
            **context,
            "event": "analysis.completed",
            "analysis_id": persisted.analysis.pk,
            "status": status,
        },
    )
    relevance = "релевантен" if persisted.analysis.is_relevant else "не релевантен"
    record_monitoring_event(
        component=MonitoringComponent.AI,
        status=MonitoringEventStatus.SUCCESS,
        source=source_post.source,
        message=f"Пост {source_post.external_id} проанализирован: {relevance}.",
        task_id=_task_id(task),
    )
    return {
        "status": status,
        "source_post_id": source_post.pk,
        "analysis_id": persisted.analysis.pk,
        "is_relevant": bool(persisted.analysis.is_relevant),
        "queued_deliveries": queued_deliveries,
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
    source_post: SourcePost,
    configuration: SystemConfiguration,
    exc: Exception,
    raw_response: object | None,
    context: dict[str, object],
) -> dict[str, int | str]:
    retries = getattr(task.request, "retries", 0)
    if retries < configuration.retry_count:
        countdown = min(_BASE_RETRY_SECONDS * (2**retries), _MAX_RETRY_SECONDS)
        record_monitoring_event(
            component=MonitoringComponent.AI,
            status=MonitoringEventStatus.ERROR,
            source=source_post.source,
            message=(
                f"Временная ошибка анализа поста {source_post.external_id}: {exc}. "
                f"Повтор через {countdown} сек."
            ),
            error_type=type(exc).__name__,
            task_id=_task_id(task),
        )
        logger.warning(
            "Temporary or invalid LLM response; retry scheduled.",
            extra={
                **context,
                "event": "analysis.retry_scheduled",
                "status": "retry",
                "error_type": type(exc).__name__,
            },
        )
        raise task.retry(
            exc=exc,
            countdown=countdown,
            max_retries=configuration.retry_count,
        )

    analysis = save_failed_analysis(
        source_post_id=source_post.pk,
        configuration=configuration,
        error=str(exc),
        raw_response=raw_response,
    )
    logger.error(
        "Post analysis retries exhausted.",
        extra={
            **context,
            "event": "analysis.retries_exhausted",
            "analysis_id": analysis.pk,
            "status": "failed",
            "error_type": type(exc).__name__,
        },
    )
    record_monitoring_event(
        component=MonitoringComponent.AI,
        status=MonitoringEventStatus.ERROR,
        source=source_post.source,
        message=f"Ошибка анализа поста {source_post.external_id}: {exc}",
        error_type=type(exc).__name__,
        task_id=_task_id(task),
    )
    return _failure_result(source_post_id=source_post.pk, analysis=analysis)


def _failure_result(
    *,
    source_post_id: int,
    analysis: Analysis,
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


def _task_id(task: Task) -> str:
    return str(getattr(task.request, "id", "") or "")
