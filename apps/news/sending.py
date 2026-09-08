"""Journal before networking; never retry an ambiguous Telegram send."""
from datetime import timedelta
from django.db import transaction
from django.utils import timezone
from .cache import cleanup_sent, ensure_uploads
from .locks import publication_lock
from .models import NewsConfiguration, NewsDelivery, NewsPublication
from .payload import publication_hash, publication_expired, publication_allowed
from .scheduling import fill_ready, reserve_day
from .transport import NewsTransport, DeliveryRejected, DeliveryRateLimited, RemoteMediaRejected


def deliver(publication_id):
    with publication_lock(publication_id) as acquired:
        if acquired:
            deliver_locked(publication_id)


def deliver_locked(publication_id):
    initial = NewsPublication.objects.select_related("target", "event", "initial_fill").get(pk=publication_id)
    config = NewsConfiguration.load()
    if initial.status != "ready" or not publication_allowed(initial, config):
        return
    if initial.next_attempt_at and initial.next_attempt_at > timezone.now():
        return
    if publication_expired(initial, timezone.now()):
        NewsPublication.objects.filter(pk=publication_id, status="ready").update(status="blocked", last_error="Новость устарела.")
        return
    if initial.initial_fill_id and not fill_ready(initial, timezone.now()):
        return  # Wait for the previous historical post and for the pause between them.
    try:
        with NewsTransport() as transport:
            if initial.upload_media and not prepare_uploads(initial, transport.bot_identity):
                return
            transport.prepare(initial)
            with transaction.atomic():
                config = NewsConfiguration.objects.select_for_update(of=("self",)).select_related("target").get(pk=1)
                publication = NewsPublication.objects.select_for_update(of=("self",)).select_related(
                    "target", "event", "initial_fill").get(pk=publication_id)
                now = timezone.now()
                if publication.status != "ready" or not publication_allowed(publication, config):
                    return
                if transport.payload["chat_id"] != publication.target.telegram_chat_id:
                    return
                if publication_expired(publication, now) or publication_hash(publication) != initial.payload_hash:
                    publication.status, publication.last_error = "blocked", "Новость устарела или изменена."
                    publication.save()
                    return
                if publication.initial_fill_id and not fill_ready(publication, now):
                    return
                if not reserve_day(publication, config, now):
                    return
                publication.status, publication.lease_until = "sending", now + timedelta(minutes=5)
                publication.save()
                receipt, _ = NewsDelivery.objects.get_or_create(publication=publication)
                receipt.attempts += 1
                receipt.save()
            try:
                result = transport.send()
            except RemoteMediaRejected:
                finish(publication_id, "ready", "Telegram не скачал URL; следующая попытка загрузит оригинал.", upload_media=True)
                return
            except DeliveryRateLimited as exc:
                finish(publication_id, "ready", "Telegram ограничил частоту отправки.",
                       next_attempt_at=timezone.now()+timedelta(seconds=exc.seconds))
                return
            except DeliveryRejected:
                finish(publication_id, "blocked", "Telegram отклонил публикацию.")
                return
            except Exception:
                finish(publication_id, "uncertain", "Результат неизвестен. Требуется проверка канала.")
                return
            with transaction.atomic():
                publication = NewsPublication.objects.select_for_update().get(pk=publication_id)
                publication.status, publication.lease_until, publication.last_error = "sent", None, ""
                publication.save()
                NewsDelivery.objects.filter(publication=publication).update(
                    message_ids=result.message_ids, sent_at=timezone.now(), last_error="", next_attempt_at=None)
                for asset, file_id in zip(transport.assets, result.file_ids):
                    if file_id:
                        publication.media.filter(pk=asset.pk).update(
                            telegram_file_id=file_id, telegram_bot_identity=transport.bot_identity)
        cleanup_sent()
    except Exception as exc:
        # After a request, leave SENDING for recovery as UNCERTAIN.
        NewsPublication.objects.filter(pk=publication_id, status="ready").update(
            status="blocked" if isinstance(exc, ValueError) else "ready",
            next_attempt_at=timezone.now()+timedelta(minutes=5),
            last_error=f"Отправка не началась: {type(exc).__name__}.")


def prepare_uploads(publication, bot_identity):
    try:
        ensure_uploads(publication, bot_identity)
    except Exception as exc:
        publication.media_attempts += 1
        publication.status = "blocked" if publication.media_attempts >= 3 else "ready"
        publication.next_attempt_at = timezone.now()+timedelta(minutes=5)
        publication.last_error = f"Оригинал не загружен: {type(exc).__name__}."
        publication.save(update_fields=("media_attempts", "status", "next_attempt_at", "last_error"))
        return False
    return True


@transaction.atomic
def finish(publication_id, status, error, next_attempt_at=None, upload_media=False):
    publication = NewsPublication.objects.select_for_update().get(pk=publication_id)
    if publication.status != "sending":
        return
    publication.status, publication.last_error = status, error
    publication.upload_media = publication.upload_media or upload_media
    publication.lease_until, publication.next_attempt_at = None, next_attempt_at
    publication.save()
    NewsDelivery.objects.filter(publication=publication).update(last_error=error, next_attempt_at=next_attempt_at)


@transaction.atomic
def resolve(delivery_id, *, was_sent, note):
    if not note.strip():
        raise ValueError("Сначала запишите результат проверки канала.")
    publication_id = NewsDelivery.objects.values_list("publication_id", flat=True).get(pk=delivery_id)
    publication = NewsPublication.objects.select_for_update().get(pk=publication_id)
    receipt = NewsDelivery.objects.select_for_update().get(pk=delivery_id)
    if publication.status != "uncertain":
        raise ValueError("Разрешать можно только неизвестный результат.")
    if was_sent and not receipt.message_ids:
        raise ValueError("Для подтверждённой отправки укажите ID сообщений Telegram.")
    receipt.resolution_note, receipt.last_error = note, ""
    if was_sent:
        receipt.sent_at = receipt.sent_at or timezone.now()
    receipt.save()
    publication.status = "sent" if was_sent else "ready"
    publication.last_error, publication.next_attempt_at = "", None
    publication.payload_hash = publication_hash(publication)
    publication.save()
    if was_sent:
        transaction.on_commit(cleanup_sent, robust=True)
