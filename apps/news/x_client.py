"""X search with a bounded result page and no billable user expansions."""
from decimal import Decimal
import re

from apps.monitoring.x_api import XApiClient, XApiResponseError, XTimelinePage
from .budget import reserve, settle

PAGE_SIZE = 10
FIELDS = "id,text,created_at,author_id,entities,referenced_tweets,note_tweet,attachments,edit_history_tweet_ids"
MEDIA_FIELDS = "media_key,type,url,preview_image_url,alt_text,variants"


def build_query(subscription):
    username = subscription.source.username
    if not re.fullmatch(r"[A-Za-z0-9_]{1,15}", username):
        raise ValueError("Недопустимое имя X-источника.")
    query = f"from:{username} -is:retweet"
    terms = subscription.query_terms.strip()
    if terms:
        if not re.fullmatch(r'[A-Za-z0-9_ -]+', terms):
            raise ValueError("Фильтр принимает только слова через пробел.")
        query += " (" + " OR ".join(terms.split()) + ")"
    return query


def fetch_page(subscription, checkpoint, config, *, initial_fill_id=None):
    query = build_query(subscription)
    params = {
        "query": query, "max_results": PAGE_SIZE, "sort_order": "recency",
        "tweet.fields": FIELDS, "expansions": "attachments.media_keys",
        "media.fields": MEDIA_FIELDS,
        "start_time": checkpoint.window_start.isoformat(),
        "end_time": checkpoint.window_end.isoformat(),
    }
    if checkpoint.next_token:
        params["next_token"] = checkpoint.next_token
    with XApiClient() as client:
        usage = reserve(subscription.source, config, maximum=Decimal("0.050"),
                        priority=subscription.priority, initial_fill_id=initial_fill_id,
                        operation="initial_fill" if initial_fill_id else "recent_search")
        try:
            payload = client._get_json("/2/tweets/search/recent", params=params)
            posts = payload.get("data") or []
            if not isinstance(posts, list) or any(not isinstance(p, dict) for p in posts):
                raise XApiResponseError("Неверный формат страницы X.")
            includes = payload.get("includes") or {}
            meta = payload.get("meta") or {}
            if not isinstance(includes, dict) or not isinstance(meta, dict):
                raise XApiResponseError("Неверные метаданные X.")
            # Unexpected resources remain charged conservatively, never discarded as free.
            count = len(posts) + len(includes.get("tweets") or [])
            if count > PAGE_SIZE or includes.get("users"):
                raise XApiResponseError("X вернул незапрошенные платные профили.")
            settle(usage.pk, resources=count)
            return XTimelinePage(tuple(posts), includes, meta, tuple(payload.get("errors") or []))
        except Exception:
            settle(usage.pk, resources=None)
            raise
