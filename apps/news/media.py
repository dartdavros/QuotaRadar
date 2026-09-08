"""Preserve original attachments; reject incomplete or unsupported media."""
from urllib.parse import urlsplit
from .models import MediaAsset
from .errors import NewsPolicyError

HOSTS = {"pbs.twimg.com", "video.twimg.com"}
LIMITS = {"photo": 10_000_000, "video": 49_000_000, "animation": 49_000_000}

def validate_url(url):
    try:
        parsed = urlsplit(url)
        valid = (parsed.scheme == "https" and parsed.hostname in HOSTS
                 and parsed.port in (None, 443) and not parsed.username and not parsed.password)
    except (TypeError, ValueError):
        valid = False
    if not valid:
        raise NewsPolicyError("Медиа разрешены только с HTTPS-хостов X.")

def attachment_plan(post):
    raw = post.raw_data
    attachments = raw.get("post", {}).get("attachments", {}).get("media_keys", [])
    if not isinstance(attachments, list):
        raise NewsPolicyError("Некорректный список медиа.")
    media = {m.get("media_key"): m for m in raw.get("includes", {}).get("media", []) if isinstance(m, dict)}
    result = []
    for key in attachments:
        item = media.get(key)
        if not item:
            raise NewsPolicyError("X не вернул оригинальное вложение.")
        kind = item.get("type")
        if kind == "photo":
            url = item.get("url")
        elif kind in ("video", "animated_gif"):
            variants = [v for v in item.get("variants", [])
                        if v.get("content_type") == "video/mp4" and isinstance(v.get("url"), str)]
            if not variants:
                raise NewsPolicyError("X не вернул MP4 оригинала; превью не заменяет видео.")
            url = max(variants, key=lambda v: v.get("bit_rate", 0)).get("url")
            kind = "animation" if kind == "animated_gif" else "video"
        else:
            raise NewsPolicyError("Неподдерживаемый тип оригинального медиа.")
        validate_url(url)
        result.append((key, kind, url))
    if len(result) > 10 or (len(result) > 1 and any(kind == "animation" for _, kind, _ in result)):
        raise NewsPolicyError("Оригинальные вложения нельзя отправить одним альбомом Telegram.")
    return result

def preserve(publication, posts):
    # Copy all attachments from one original, not duplicate repost media.
    primary = next((post for post in posts if post.raw_data.get("post", {}).get("attachments", {}).get("media_keys")), None)
    if primary is None:
        return
    plan = attachment_plan(primary)
    for position, (key, kind, url) in enumerate(plan):
        MediaAsset.objects.get_or_create(publication=publication, media_key=key,
            defaults={"post": primary, "position": position, "kind": kind, "url": url})
