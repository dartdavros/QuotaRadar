"""Conservative signals for reviewing refusals, never for publishing a post."""

import re

from apps.sources.models import SourcePost, SourceProvider

CODEX_RESET_AUTHOR_ID = "1953337039510003712"

_TRUSTED_SOURCES = {
    SourceProvider.OPENAI: {"openaidevs", "thsottiaux", "sama"},
    SourceProvider.ANTHROPIC: {"claudedevs"},
}
_RESET = re.compile(r"\breset(?:s|ting)?\b", re.IGNORECASE)
_MASS = re.compile(
    r"\b(?:global|all|everyone|everybody|users|plans|plus|pro|business|enterprise|edu)\b",
    re.IGNORECASE,
)
_QUOTA = re.compile(r"\b(?:limits?|quota|usage|tokens?|credits?)\b", re.IGNORECASE)
_EXCLUDED = re.compile(
    r"\b(?:git|api|rpm|rpd|tpm|infrastructure|password|factory|settings)\b"
    r"|\bHTTP\s*429\b|\bhard[ -]?reset\b"
    r"|\b(?:my|one|single|individual)\s+(?:account|user|limits?|quota)\b",
    re.IGNORECASE,
)
# X keeps typographic apostrophes; a clause break ends a negation ("but no, it's reset").
_UNCERTAIN = re.compile(
    r"\?|\b(?:should|could|might|maybe|wish|wonder|hope)\b"
    r"|\b(?:not|never|no|cannot|(?:won|don|didn|can)['’]t)\b[^.!?,;:—\n]{0,40}\breset",
    re.IGNORECASE,
)


def is_verified_codex_reset_source(post: SourcePost) -> bool:
    """Bind the rule to X's stable author ID, not a reusable account handle."""

    raw = post.raw_data if isinstance(post.raw_data, dict) else {}
    primary = raw.get("post") or {}
    if not isinstance(primary, dict):
        return False
    return (
        post.source.provider == SourceProvider.OPENAI
        and post.source.x_user_id == CODEX_RESET_AUTHOR_ID
        and primary.get("author_id") == CODEX_RESET_AUTHOR_ID
        and primary.get("id") == post.external_id
        and not any(
            isinstance(ref, dict) and ref.get("type") == "retweeted"
            for ref in primary.get("referenced_tweets") or []
        )
    )


def has_reset_exclusions(text: str) -> bool:
    return bool(_EXCLUDED.search(text) or _UNCERTAIN.search(text))


def needs_reset_review(post: SourcePost) -> bool:
    """Only inspect the source's own words, excluding quoted/parent claims."""

    text = post.text
    if is_verified_codex_reset_source(post):
        # The review must itself confirm quota_reset, so it judges questions and negations.
        return bool(_RESET.search(text) and not _EXCLUDED.search(text))
    trusted = _TRUSTED_SOURCES.get(post.source.provider, set())
    if post.source.username.casefold() not in trusted:
        return False
    return bool(
        _RESET.search(text)
        and _MASS.search(text)
        and _QUOTA.search(text)
        and not has_reset_exclusions(text)
    )
