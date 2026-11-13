"""Persisted claims and outcomes for the one-time private-chat announcement."""

from datetime import timedelta

from django.db.models import F, Q
from django.utils import timezone

from .client import (
    TelegramAuthenticationError,
    TelegramBotApiClient,
    TelegramConfigurationError,
    TelegramPermanentChatError,
    TelegramResponseError,
    TelegramTemporaryError,
)
from .models import (
    DeliveryTarget,
    DeliveryTargetType,
    PrivateChatRetirementNotice,
    RetirementNoticeStatus as Status,
)
from .retirement import RETIREMENT_MESSAGE


def private_recipients():
    # Include /stop and blocked subscribers; never include group/channel IDs.
    return DeliveryTarget.objects.filter(
        target_type=DeliveryTargetType.PRIVATE_CHAT,
        telegram_chat_id__regex=r"^[1-9][0-9]*$",
    )


def send_retirement_notice(*, target_id: int, client: TelegramBotApiClient) -> str:
    target = private_recipients().filter(pk=target_id).first()
    if target is None:
        return "skipped"
    notice, _ = PrivateChatRetirementNotice.objects.get_or_create(target=target)
    now = timezone.now()
    claimed = PrivateChatRetirementNotice.objects.filter(
        pk=notice.pk, status=Status.PENDING,
    ).filter(Q(next_attempt_at__isnull=True) | Q(next_attempt_at__lte=now)).update(
        status=Status.SENDING, attempts=F("attempts") + 1,
        next_attempt_at=None, last_error="", updated_at=now,
    )
    if not claimed:
        notice.refresh_from_db()
        return notice.status

    # Commit the claim before HTTP. A crash or an ambiguous response must not
    # cause another send: SENDING and UNCERTAIN require manual investigation.
    try:
        message_id = client.send_message(chat_id=target.telegram_chat_id, text=RETIREMENT_MESSAGE)
    except TelegramPermanentChatError as exc:
        return _finish(notice.pk, Status.UNREACHABLE, last_error=str(exc))
    except TelegramTemporaryError as exc:
        if exc.delivery_uncertain:
            return _finish(notice.pk, Status.UNCERTAIN, last_error=str(exc))
        return _finish(
            notice.pk, Status.PENDING, last_error=str(exc),
            next_attempt_at=timezone.now() + timedelta(seconds=exc.retry_after or 60),
        )
    except (TelegramAuthenticationError, TelegramConfigurationError) as exc:
        _finish(notice.pk, Status.PENDING, last_error=str(exc))
        raise
    except TelegramResponseError as exc:
        _finish(notice.pk, Status.UNCERTAIN, last_error=str(exc))
        raise
    return _finish(notice.pk, Status.SENT, telegram_message_id=message_id, sent_at=timezone.now())


def _finish(notice_id: int, status: str, **fields) -> str:
    PrivateChatRetirementNotice.objects.filter(pk=notice_id, status=Status.SENDING).update(
        status=status, updated_at=timezone.now(), **fields,
    )
    return status
