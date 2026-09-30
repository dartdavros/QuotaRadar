"""Generate only missing media and durably reuse it across workers and delivery retries."""
from hashlib import sha256
import json

from django.db import transaction
from django.utils import timezone

from .cover_art import asset_metadata, compose, cover_prompt, reference_image
from .cover_brands import official_logo
from .cover_client import CoverBlocked, generate, validate_provider
from .models import MediaAsset, NewsConfiguration, NewsPublication
from .payload import publication_allowed, publication_expired


def claim_generation(publication, config):
    with transaction.atomic():
        current = NewsPublication.objects.select_for_update().get(pk=publication.pk)
        config = NewsConfiguration.load()
        if current.media.exists():
            return False
        if (current.status != "preparing" or current.attempts != publication.attempts
                or not publication_allowed(current, config) or publication_expired(current, timezone.now())):
            raise CoverBlocked("Публикация больше не допускает подготовку обложки.")
        if current.cover_requested_at:
            raise CoverBlocked("Обложка уже запрашивалась, но не сохранена. Платный автоповтор отключён.")
        current.cover_requested_at = timezone.now()
        current.save(update_fields=("cover_requested_at",))
    return True


def source_digest(publication, posts):
    return sha256(json.dumps({"product": publication.event.product,
        "sources": [(post.pk, post.normalized_text) for post in posts]}, ensure_ascii=False).encode()).hexdigest()


def ensure_cover(publication, config, writing, posts):
    existing = publication.media.first()
    if existing:
        if (existing.origin == "generated"
                and existing.generation_metadata.get("source_digest") != source_digest(publication, posts)):
            raise CoverBlocked("Первоисточники готовой обложки изменились. Требуется проверка владельца.")
        return
    brand, logo_path = official_logo(publication.event.product, posts)
    validate_provider()
    reference = reference_image()
    prompt = cover_prompt(publication, writing)
    if not claim_generation(publication, config):
        return
    try:
        image = generate(prompt, reference)
        content = compose(image.content, logo_path)
        metadata = asset_metadata(brand, logo_path, prompt, image)
        metadata["source_digest"] = source_digest(publication, posts)
        checksum = sha256(content).hexdigest()
        with transaction.atomic():
            # Save an obtained image even if publishing was disabled while the API was running.
            # The preparation/delivery gates still forbid sending; the paid result is reusable.
            current = NewsPublication.objects.select_for_update().get(pk=publication.pk)
            if not current.media.exists():
                MediaAsset.objects.create(publication=current, post=posts[0], position=0, kind="photo",
                    media_key=f"cover-v1:{checksum}", origin="generated", generated_content=content,
                    checksum=checksum, size=len(content), generation_metadata=metadata)
    except CoverBlocked:
        raise
    except Exception:
        raise CoverBlocked("Обложка не сохранена. Платный автоповтор отключён; требуется проверка.") from None
