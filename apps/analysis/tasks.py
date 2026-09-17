"""Celery task for idempotent LLM interpretation of source posts."""

from __future__ import annotations

import logging

from celery import Task, shared_task
from django.utils import timezone

from apps.configuration.models import SystemConfiguration
from apps.monitoring.events import record_monitoring_event
from apps.monitoring.models import MonitoringComponent, MonitoringEventStatus
from apps.sources.models import SourcePost, SourcePostProcessingStatus
from apps.sources.routing import accepts_quota
from apps.telegram.services import queue_analysis_deliveries

from .availability import record_llm_failure, record_llm_success
from .fallback import deliver_without_llm
from .failures import permanent_failure, retry_or_fail, task_id
from .llm import LlmError, LlmTemporaryError, create_llm_client
from .locks import source_post_analysis_lock
from .prompts import PromptConfigurationError, render_prompt
from .quality import AnalysisQualityError, validate_payload_for_post
from .services import find_successful_analysis, save_successful_analysis

logger = logging.getLogger(__name__)


@shared_task(bind=True, name="analysis.analyze_post")
def analyze_post(self: Task, source_post_id: int) -> dict[str, int | str | bool]:
    """Analyze one post once, retrying only temporary or invalid LLM responses."""

    try:
        source_post = SourcePost.objects.select_related("source").get(pk=source_post_id)
    except SourcePost.DoesNotExist:
        return {"status": "missing", "source_post_id": source_post_id}

    if not accepts_quota(source_post.source_id):
        return {"status": "disabled", "source_post_id": source_post_id}

    context = {
        "event": "analysis.started",
        "task_id": task_id(self),
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
        record_llm_success()
        raw_response = response.raw_response
        validate_payload_for_post(payload=response.payload, source_post=source_post)
    except LlmError as exc:
        # Any LLM failure counts: timeout, 429, 5xx, rejected key, dead proxy,
        # unusable answer. Two in a row and the post is warned about without it.
        raw_response = getattr(exc, "raw_response", raw_response)
        record_llm_failure()
        fallback = deliver_without_llm(
            source_post=source_post,
            configuration=configuration,
            task_id=task_id(task),
        )
        if fallback is not None:
            return fallback
        if isinstance(exc, LlmTemporaryError):
            return retry_or_fail(
                task=task,
                source_post=source_post,
                configuration=configuration,
                exc=exc,
                raw_response=raw_response,
                context=context,
            )
        return permanent_failure(
            task=task,
            source_post=source_post,
            configuration=configuration,
            exc=exc,
            raw_response=raw_response,
            context=context,
        )
    except AnalysisQualityError as exc:
        return retry_or_fail(
            task=task,
            source_post=source_post,
            configuration=configuration,
            exc=exc,
            raw_response=raw_response,
            context=context,
        )
    except PromptConfigurationError as exc:
        return permanent_failure(
            task=task,
            source_post=source_post,
            configuration=configuration,
            exc=exc,
            raw_response=raw_response,
            context=context,
        )

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
        task_id=task_id(task),
    )
    return {
        "status": status,
        "source_post_id": source_post.pk,
        "analysis_id": persisted.analysis.pk,
        "is_relevant": bool(persisted.analysis.is_relevant),
        "queued_deliveries": queued_deliveries,
    }
