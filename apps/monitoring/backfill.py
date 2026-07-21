"""Bounded historical import for already initialized X sources."""

from __future__ import annotations

from dataclasses import dataclass

from django.db import transaction

from apps.configuration.models import SystemConfiguration
from apps.sources.models import Source, SourcePost

from .services import persist_source_posts, prepare_source_posts
from .x_api import XApiClient, XApiResponseError

_X_TIMELINE_PAGE_SIZE = 100


class BackfillUnavailableError(ValueError):
    """Historical import cannot start before an initial source cursor exists."""


@dataclass(frozen=True, slots=True)
class BackfillResult:
    source_id: int
    pages: int
    created_posts: int
    existing_posts: int
    ignored_retweets: int
    created_post_ids: tuple[int, ...]
    history_cursor: str


def ingest_source_history(
    source: Source,
    client: XApiClient,
    configuration: SystemConfiguration,
) -> BackfillResult:
    """Import one bounded batch older than the oldest stored source post."""

    if not source.x_user_id:
        raise ValueError("Source X User ID is required before historical import.")

    history_cursor = _resolve_history_cursor(source)
    until_id = _exclusive_upper_bound(history_cursor)
    limit = configuration.historical_backfill_post_limit
    pages = list(
        client.iter_user_posts(
            source.x_user_id,
            since_id=None,
            until_id=until_id,
            max_results=min(limit, _X_TIMELINE_PAGE_SIZE),
            max_pages=None,
            max_total_results=limit,
        )
    )
    prepared, ignored_retweets, _ = prepare_source_posts(source, pages)

    with transaction.atomic():
        locked_source = Source.objects.select_for_update().get(pk=source.pk)
        persistence = persist_source_posts(
            source=locked_source,
            prepared=prepared,
        )

    return BackfillResult(
        source_id=source.pk,
        pages=len(pages),
        created_posts=persistence.created_posts,
        existing_posts=persistence.existing_posts,
        ignored_retweets=ignored_retweets,
        created_post_ids=persistence.created_post_ids,
        history_cursor=history_cursor,
    )


def _resolve_history_cursor(source: Source) -> str:
    oldest_post_id = (
        SourcePost.objects.filter(source_id=source.pk)
        .order_by("published_at", "external_id")
        .values_list("external_id", flat=True)
        .first()
    )
    cursor = oldest_post_id or source.last_post_id
    if not cursor:
        raise BackfillUnavailableError(
            "Historical import requires at least one stored post or source cursor."
        )
    return cursor


def _exclusive_upper_bound(cursor: str) -> str:
    if not cursor.isdigit():
        raise XApiResponseError("Stored X Post history cursor is invalid.")
    numeric_cursor = int(cursor)
    if numeric_cursor <= 1:
        raise BackfillUnavailableError("No older X Post ID can be requested.")
    return str(numeric_cursor - 1)
