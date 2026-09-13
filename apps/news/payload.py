"""Freeze editorial content and media identity independently of temporary cache files."""
from hashlib import sha256
import json
from django.conf import settings


def publication_hash(publication, rendered=None):
    return sha256(json.dumps({
        "html": publication.rendered if rendered is None else rendered,
        "media": list(publication.media.values("kind", "position", "url", "media_key")),
    }, sort_keys=True).encode()).hexdigest()


def publication_expired(publication, now):
    deadline = publication.initial_fill.expires_at if publication.initial_fill_id else publication.event.expires_at
    return deadline <= now


def publication_allowed(publication, config):
    if (not config.publishing_enabled or config.target_id != publication.target_id
            or not publication.target.enabled or publication.target.feed != "news"
            or publication.target.target_type != "channel"):
        return False
    if publication.initial_fill_id:
        return (settings.QUOTARADAR_NEWS_INITIAL_FILL_ALLOWED and config.collection_enabled
                and config.analysis_enabled and publication.initial_fill.status not in ("blocked", "completed"))
    return True
