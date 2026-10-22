"""Text extraction and URL expansion shared by posts and reply context."""

import re
from typing import Any

_WHITESPACE_PATTERN = re.compile(r"[ \t]+")
_ARTICLE_TEXT_KEYS = (
    "title",
    "preview_text",
    "description",
    "text",
    "plain_text",
    "content",
)


def preferred_post_text(post: dict[str, Any]) -> str:
    note_tweet = post.get("note_tweet")
    if isinstance(note_tweet, dict):
        note_text = note_tweet.get("text")
        if isinstance(note_text, str) and note_text.strip():
            return clean_text(note_text)
    text = post.get("text")
    return clean_text(text) if isinstance(text, str) else ""


def clean_text(value: str) -> str:
    lines = [_WHITESPACE_PATTERN.sub(" ", line).strip() for line in value.splitlines()]
    return "\n".join(line for line in lines if line).strip()


def entity_urls(post: dict[str, Any]) -> list[dict[str, str]]:
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


def expand_urls(text: str, urls: list[dict[str, str]]) -> str:
    expanded_text = text
    for url in urls:
        expanded_text = expanded_text.replace(url["short"], url["expanded"])
    return expanded_text


def extract_article_text(article: Any) -> str:
    if not isinstance(article, dict):
        return ""
    values: list[str] = []
    for key in _ARTICLE_TEXT_KEYS:
        value = article.get(key)
        if isinstance(value, str) and value.strip():
            cleaned = clean_text(value)
            if cleaned and cleaned not in values:
                values.append(cleaned)
    return "\n".join(values)

