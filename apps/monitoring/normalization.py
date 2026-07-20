"""Normalize X API post payloads into deterministic text for later analysis."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from django.utils.dateparse import parse_datetime

from apps.sources.models import Source

_WHITESPACE_PATTERN = re.compile(r"[ \t]+")
_ARTICLE_TEXT_KEYS = (
    "title",
    "preview_text",
    "description",
    "text",
    "plain_text",
    "content",
)


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

    primary_text = _preferred_post_text(post)
    if not primary_text:
        raise XPostPayloadError("X post text is missing.")

    normalized_sections: list[str] = []
    normalized_sections.append(_expand_urls(primary_text, _entity_urls(post)))

    article_text = _extract_article_text(post.get("article"))
    if article_text:
        normalized_sections.append(f"Article:\n{article_text}")

    quoted_posts = _quoted_posts(post, included_posts)
    for quoted in quoted_posts:
        quoted_text = _expand_urls(_preferred_post_text(quoted), _entity_urls(quoted))
        if quoted_text:
            normalized_sections.append(f"Quoted post:\n{quoted_text}")
        quoted_article = _extract_article_text(quoted.get("article"))
        if quoted_article:
            normalized_sections.append(f"Quoted article:\n{quoted_article}")

    expanded_urls = _collect_expanded_urls(post, quoted_posts)
    if expanded_urls:
        normalized_sections.append("Expanded URLs:\n" + "\n".join(expanded_urls))

    alt_texts, attached_media = _attached_media(
        [post, *quoted_posts],
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


def _preferred_post_text(post: dict[str, Any]) -> str:
    note_tweet = post.get("note_tweet")
    if isinstance(note_tweet, dict):
        note_text = note_tweet.get("text")
        if isinstance(note_text, str) and note_text.strip():
            return _clean_text(note_text)
    text = post.get("text")
    return _clean_text(text) if isinstance(text, str) else ""


def _clean_text(value: str) -> str:
    lines = [_WHITESPACE_PATTERN.sub(" ", line).strip() for line in value.splitlines()]
    return "\n".join(line for line in lines if line).strip()


def _entity_urls(post: dict[str, Any]) -> list[dict[str, str]]:
    entities: list[Any] = []
    if isinstance(post.get("entities"), dict):
        entities.append(post["entities"])
    note_tweet = post.get("note_tweet")
    if isinstance(note_tweet, dict) and isinstance(note_tweet.get("entities"), dict):
        entities.append(note_tweet["entities"])

    result: list[dict[str, str]] = []
    for entity_group in entities:
        for item in entity_group.get("urls") or []:
            if not isinstance(item, dict):
                continue
            short = item.get("url")
            expanded = item.get("unwound_url") or item.get("expanded_url") or short
            if isinstance(short, str) and isinstance(expanded, str):
                result.append({"short": short, "expanded": expanded})
    return result


def _expand_urls(text: str, urls: list[dict[str, str]]) -> str:
    expanded_text = text
    for url in urls:
        expanded_text = expanded_text.replace(url["short"], url["expanded"])
    return expanded_text


def _collect_expanded_urls(
    post: dict[str, Any],
    quoted_posts: list[dict[str, Any]],
) -> list[str]:
    result: list[str] = []
    for item in (post, *quoted_posts):
        for url in _entity_urls(item):
            expanded = url["expanded"]
            if expanded and expanded not in result:
                result.append(expanded)
    return result


def _extract_article_text(article: Any) -> str:
    if not isinstance(article, dict):
        return ""
    values: list[str] = []
    for key in _ARTICLE_TEXT_KEYS:
        value = article.get(key)
        if isinstance(value, str) and value.strip():
            cleaned = _clean_text(value)
            if cleaned and cleaned not in values:
                values.append(cleaned)
    return "\n".join(values)


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


def _quoted_posts(
    post: dict[str, Any],
    included_posts: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for reference in post.get("referenced_tweets") or []:
        if not isinstance(reference, dict) or reference.get("type") != "quoted":
            continue
        referenced_id = reference.get("id")
        if isinstance(referenced_id, str) and referenced_id in included_posts:
            result.append(included_posts[referenced_id])
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
                cleaned = _clean_text(alt_text)
                if cleaned not in alt_texts:
                    alt_texts.append(cleaned)
    return alt_texts, media_items


def _deduplicate_sections(sections: list[str]) -> list[str]:
    result: list[str] = []
    for section in sections:
        if section and section not in result:
            result.append(section)
    return result
