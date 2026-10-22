"""Normalize X API post payloads into deterministic text for later analysis."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from django.utils.dateparse import parse_datetime

from apps.sources.models import Source

from .normalization_text import (
    clean_text, entity_urls, expand_urls, extract_article_text, preferred_post_text,
)
from .reply_context import referenced_posts, reply_sections


class XPostPayloadError(ValueError):
    """Raised when a post cannot be converted into a valid SourcePost payload."""


@dataclass(frozen=True, slots=True)
class NormalizedSourcePost:
    external_id: str
    text: str
    normalized_text: str
    source_url: str
    published_at: datetime
    raw_data: dict[str, Any]


def is_retweet(post: dict[str, Any]) -> bool:
    references = post.get("referenced_tweets") or []
    return any(
        isinstance(reference, dict) and reference.get("type") == "retweeted"
        for reference in references
    )


def normalize_source_post(
    *,
    source: Source,
    post: dict[str, Any],
    includes: dict[str, Any],
    response_meta: dict[str, Any] | None = None,
    response_errors: tuple[dict[str, Any], ...] = (),
) -> NormalizedSourcePost:
    external_id = post.get("id")
    if not isinstance(external_id, str) or not external_id:
        raise XPostPayloadError("X post ID is missing.")
    if not external_id.isdigit():
        raise XPostPayloadError("X post ID is invalid.")

    published_at = _parse_published_at(post.get("created_at"))
    included_posts = _included_posts_by_id(includes)
    included_media = _included_media_by_key(includes)

    primary_text = preferred_post_text(post)
    if not primary_text:
        raise XPostPayloadError("X post text is missing.")

    normalized_sections: list[str] = []
    normalized_sections.append(expand_urls(primary_text, entity_urls(post)))

    article_text = extract_article_text(post.get("article"))
    if article_text:
        normalized_sections.append(f"Article:\n{article_text}")

    quoted_posts = referenced_posts(post, included_posts, "quoted")
    for quoted in quoted_posts:
        quoted_text = expand_urls(preferred_post_text(quoted), entity_urls(quoted))
        if quoted_text:
            normalized_sections.append(f"Quoted post:\n{quoted_text}")
        quoted_article = extract_article_text(quoted.get("article"))
        if quoted_article:
            normalized_sections.append(f"Quoted article:\n{quoted_article}")

    reply_parents = referenced_posts(post, included_posts, "replied_to")
    normalized_sections.extend(reply_sections(
        parents=reply_parents, post=post, includes=includes, source=source,
    ))
    context_posts = [*quoted_posts, *reply_parents]
    expanded_urls = _collect_expanded_urls(post, context_posts)
    if expanded_urls:
        normalized_sections.append("Expanded URLs:\n" + "\n".join(expanded_urls))

    alt_texts, attached_media = _attached_media(
        [post, *context_posts],
        included_media,
    )
    if alt_texts:
        normalized_sections.append("Media alt text:\n" + "\n".join(alt_texts))

    normalized_text = "\n\n".join(_deduplicate_sections(normalized_sections)).strip()
    raw_data = {
        "post": post,
        "includes": includes,
        "meta": response_meta or {},
        "resolved_context": {
            "quoted_tweets": quoted_posts,
            "reply_parents": reply_parents,
            "attached_media": attached_media,
        },
        "errors": list(response_errors),
    }
    return NormalizedSourcePost(
        external_id=external_id,
        text=primary_text,
        normalized_text=normalized_text,
        source_url=f"https://x.com/{source.username}/status/{external_id}",
        published_at=published_at,
        raw_data=raw_data,
    )


def _parse_published_at(value: Any) -> datetime:
    if not isinstance(value, str):
        raise XPostPayloadError("X post publication date is missing.")
    parsed = parse_datetime(value)
    if parsed is None or parsed.tzinfo is None:
        raise XPostPayloadError("X post publication date is invalid.")
    return parsed


def _collect_expanded_urls(
    post: dict[str, Any],
    quoted_posts: list[dict[str, Any]],
) -> list[str]:
    result: list[str] = []
    for item in (post, *quoted_posts):
        for url in entity_urls(item):
            expanded = url["expanded"]
            if expanded and expanded not in result:
                result.append(expanded)
    return result


def _included_posts_by_id(includes: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for post in includes.get("tweets") or []:
        if isinstance(post, dict) and isinstance(post.get("id"), str):
            result[post["id"]] = post
    return result


def _included_media_by_key(includes: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for media in includes.get("media") or []:
        if isinstance(media, dict) and isinstance(media.get("media_key"), str):
            result[media["media_key"]] = media
    return result


def _attached_media(
    posts: list[dict[str, Any]],
    included_media: dict[str, dict[str, Any]],
) -> tuple[list[str], list[dict[str, Any]]]:
    alt_texts: list[str] = []
    media_items: list[dict[str, Any]] = []
    seen_media_keys: set[str] = set()
    for post in posts:
        attachments = post.get("attachments")
        media_keys = (
            attachments.get("media_keys") if isinstance(attachments, dict) else []
        )
        for media_key in media_keys or []:
            if not isinstance(media_key, str) or media_key in seen_media_keys:
                continue
            media = included_media.get(media_key)
            if media is None:
                continue
            seen_media_keys.add(media_key)
            media_items.append(media)
            alt_text = media.get("alt_text")
            if isinstance(alt_text, str) and alt_text.strip():
                cleaned = clean_text(alt_text)
                if cleaned not in alt_texts:
                    alt_texts.append(cleaned)
    return alt_texts, media_items


def _deduplicate_sections(sections: list[str]) -> list[str]:
    result: list[str] = []
    for section in sections:
        if section and section not in result:
            result.append(section)
    return result
