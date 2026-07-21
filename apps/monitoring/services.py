"""Idempotent source-resolution and X post ingestion services."""

from __future__ import annotations

from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone

from apps.sources.models import Source, SourcePost, SourcePostProcessingStatus

from .normalization import (
    NormalizedSourcePost,
    XPostPayloadError,
    is_retweet,
    normalize_source_post,
)
from .x_api import XApiClient, XApiResponseError, XTimelinePage

_BOOTSTRAP_MAX_RESULTS = 10
_REGULAR_POLL_MAX_RESULTS = 5


@dataclass(frozen=True, slots=True)
class ResolutionResult:
    resolved_source_ids: tuple[int, ...]
    unresolved_source_ids: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class PollResult:
    source_id: int
    pages: int
    created_posts: int
    existing_posts: int
    ignored_retweets: int
    last_post_id: str


def resolve_source_user_ids(
    *,
    client: XApiClient,
    sources: list[Source],
) -> ResolutionResult:
    """Resolve and persist X user IDs for sources that do not have one."""

    unresolved = [source for source in sources if not source.x_user_id]
    if not unresolved:
        return ResolutionResult(
            resolved_source_ids=tuple(source.pk for source in sources),
            unresolved_source_ids=(),
        )

    mapping = client.lookup_users([source.username for source in unresolved])
    checked_at = timezone.now()
    resolved_ids: list[int] = [source.pk for source in sources if source.x_user_id]
    unresolved_ids: list[int] = []
    with transaction.atomic():
        for source in unresolved:
            user_id = mapping.get(source.username.casefold())
            if user_id:
                Source.objects.filter(pk=source.pk).update(
                    x_user_id=user_id,
                    last_checked_at=checked_at,
                    last_error="",
                )
                source.x_user_id = user_id
                source.last_error = ""
                resolved_ids.append(source.pk)
            else:
                message = "X user was not returned by the user lookup endpoint."
                Source.objects.filter(pk=source.pk).update(
                    last_checked_at=checked_at,
                    last_error=message,
                )
                source.last_error = message
                unresolved_ids.append(source.pk)

    return ResolutionResult(
        resolved_source_ids=tuple(resolved_ids),
        unresolved_source_ids=tuple(unresolved_ids),
    )


def ingest_source_posts(*, source: Source, client: XApiClient) -> PollResult:
    """Fetch the bounded bootstrap or all new pages, then persist atomically."""

    if not source.x_user_id:
        raise ValueError("Source X User ID is required before polling.")

    poll_cursor = _resolve_poll_cursor(source)
    is_bootstrap = poll_cursor is None
    pages = list(
        client.iter_user_posts(
            source.x_user_id,
            since_id=poll_cursor,
            max_results=(
                _BOOTSTRAP_MAX_RESULTS
                if is_bootstrap
                else _REGULAR_POLL_MAX_RESULTS
            ),
            max_pages=1 if is_bootstrap else None,
        )
    )
    prepared, ignored_retweets, newest_external_id = _prepare_posts(source, pages)

    created_count = 0
    existing_count = 0
    completed_at = timezone.now()
    persisted_last_post_id = source.last_post_id
    with transaction.atomic():
        locked_source = Source.objects.select_for_update().get(pk=source.pk)
        for payload in prepared:
            _, created = SourcePost.objects.get_or_create(
                external_id=payload.external_id,
                defaults={
                    "source": locked_source,
                    "text": payload.text,
                    "normalized_text": payload.normalized_text,
                    "source_url": payload.source_url,
                    "published_at": payload.published_at,
                    "raw_data": payload.raw_data,
                    "processing_status": SourcePostProcessingStatus.RECEIVED,
                },
            )
            if created:
                created_count += 1
            else:
                existing_count += 1

        if poll_cursor and not locked_source.last_post_id:
            locked_source.last_post_id = poll_cursor
        if newest_external_id:
            locked_source.last_post_id = max(
                (locked_source.last_post_id, newest_external_id),
                key=_sortable_post_id,
            )
        locked_source.last_checked_at = completed_at
        locked_source.last_success_at = completed_at
        locked_source.last_error = ""
        locked_source.save(
            update_fields=(
                "last_post_id",
                "last_checked_at",
                "last_success_at",
                "last_error",
            )
        )
        persisted_last_post_id = locked_source.last_post_id

    return PollResult(
        source_id=source.pk,
        pages=len(pages),
        created_posts=created_count,
        existing_posts=existing_count,
        ignored_retweets=ignored_retweets,
        last_post_id=persisted_last_post_id,
    )


def _resolve_poll_cursor(source: Source) -> str | None:
    """Return the saved cursor or recover it from this source's stored posts."""

    if source.last_post_id:
        return source.last_post_id
    return (
        SourcePost.objects.filter(source_id=source.pk)
        .order_by("-published_at", "-external_id")
        .values_list("external_id", flat=True)
        .first()
    )


def record_source_error(source_ids: list[int] | tuple[int, ...], message: str) -> None:
    """Record a sanitized integration error without touching the success cursor."""

    Source.objects.filter(pk__in=source_ids).update(
        last_checked_at=timezone.now(),
        last_error=message,
    )


def _prepare_posts(
    source: Source,
    pages: list[XTimelinePage],
) -> tuple[list[NormalizedSourcePost], int, str]:
    prepared: list[NormalizedSourcePost] = []
    ignored_retweets = 0
    all_external_ids: list[str] = []
    for page in pages:
        for post in page.posts:
            external_id = post.get("id")
            if isinstance(external_id, str) and external_id:
                all_external_ids.append(external_id)
            if is_retweet(post):
                ignored_retweets += 1
                continue
            try:
                prepared.append(
                    normalize_source_post(
                        source=source,
                        post=post,
                        includes=page.includes,
                        response_meta=page.meta,
                        response_errors=page.errors,
                    )
                )
            except XPostPayloadError:
                raise XApiResponseError(
                    "X timeline contained invalid post data."
                ) from None

    prepared.sort(
        key=lambda item: (item.published_at, _sortable_post_id(item.external_id))
    )
    newest_external_id = max(all_external_ids, key=_sortable_post_id, default="")
    return prepared, ignored_retweets, newest_external_id


def _sortable_post_id(value: str) -> tuple[int, int | str]:
    try:
        return (1, int(value))
    except ValueError:
        return (0, value)
