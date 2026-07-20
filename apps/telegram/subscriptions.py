"""Idempotent Telegram private-chat subscription commands."""

from __future__ import annotations

from dataclasses import dataclass

from django.db import transaction

from .models import DeliveryTarget, DeliveryTargetType


class SubscriptionConflictError(RuntimeError):
    """A chat ID is already registered as a different target type."""


@dataclass(frozen=True, slots=True)
class SubscriptionResult:
    enabled: bool
    changed: bool


@transaction.atomic
def enable_private_chat(chat_id: str) -> SubscriptionResult:
    target = (
        DeliveryTarget.objects.select_for_update()
        .filter(telegram_chat_id=chat_id)
        .first()
    )
    if target is None:
        DeliveryTarget.objects.create(
            target_type=DeliveryTargetType.PRIVATE_CHAT,
            telegram_chat_id=chat_id,
            enabled=True,
        )
        return SubscriptionResult(enabled=True, changed=True)
    if target.target_type != DeliveryTargetType.PRIVATE_CHAT:
        raise SubscriptionConflictError(
            "Telegram chat ID is already registered as another target type."
        )
    if target.enabled:
        return SubscriptionResult(enabled=True, changed=False)
    target.enabled = True
    target.save(update_fields=("enabled", "updated_at"))
    return SubscriptionResult(enabled=True, changed=True)


@transaction.atomic
def disable_private_chat(chat_id: str) -> SubscriptionResult:
    target = (
        DeliveryTarget.objects.select_for_update()
        .filter(
            telegram_chat_id=chat_id,
            target_type=DeliveryTargetType.PRIVATE_CHAT,
        )
        .first()
    )
    if target is None or not target.enabled:
        return SubscriptionResult(enabled=False, changed=False)
    target.enabled = False
    target.save(update_fields=("enabled", "updated_at"))
    return SubscriptionResult(enabled=False, changed=True)


def get_private_chat_status(chat_id: str) -> SubscriptionResult:
    enabled = DeliveryTarget.objects.filter(
        telegram_chat_id=chat_id,
        target_type=DeliveryTargetType.PRIVATE_CHAT,
        enabled=True,
    ).exists()
    return SubscriptionResult(enabled=enabled, changed=False)
