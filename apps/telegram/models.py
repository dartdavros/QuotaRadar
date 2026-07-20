"""Telegram recipients and idempotent delivery journal."""

from __future__ import annotations

import re

from django.core.exceptions import ValidationError
from django.db import models

from apps.analysis.models import Analysis

_CHANNEL_USERNAME_PATTERN = re.compile(r"^@[A-Za-z0-9_]{5,32}$")
_NUMERIC_CHAT_ID_PATTERN = re.compile(r"^-?[0-9]+$")


class DeliveryTargetType(models.TextChoices):
    CHANNEL = "channel", "Канал"
    PRIVATE_CHAT = "private_chat", "Личный чат"


class DeliveryStatus(models.TextChoices):
    PENDING = "pending", "Ожидает"
    SENT = "sent", "Отправлено"
    FAILED = "failed", "Ошибка"


class DeliveryTarget(models.Model):
    """One Telegram channel or private chat that can receive notifications."""

    target_type = models.CharField(
        "Тип получателя",
        max_length=32,
        choices=DeliveryTargetType.choices,
    )
    telegram_chat_id = models.CharField(
        "Telegram chat ID или @username",
        max_length=128,
        unique=True,
    )
    enabled = models.BooleanField("Активен", default=True)
    created_at = models.DateTimeField("Создан", auto_now_add=True)
    updated_at = models.DateTimeField("Изменён", auto_now=True)

    class Meta:
        verbose_name = "Получатель Telegram"
        verbose_name_plural = "Получатели Telegram"
        ordering = ("target_type", "telegram_chat_id")
        indexes = [
            models.Index(
                fields=("enabled", "target_type"),
                name="telegram_target_enabled_idx",
            )
        ]

    def clean(self) -> None:
        super().clean()
        chat_id = self.telegram_chat_id.strip()
        self.telegram_chat_id = chat_id
        if not chat_id:
            raise ValidationError(
                {"telegram_chat_id": "Telegram chat ID не должен быть пустым."}
            )
        if self.target_type == DeliveryTargetType.PRIVATE_CHAT:
            if not chat_id.isdigit():
                raise ValidationError(
                    {
                        "telegram_chat_id": (
                            "Для личного чата требуется положительный числовой chat ID."
                        )
                    }
                )
            return
        if self.target_type == DeliveryTargetType.CHANNEL and not (
            _NUMERIC_CHAT_ID_PATTERN.fullmatch(chat_id)
            or _CHANNEL_USERNAME_PATTERN.fullmatch(chat_id)
        ):
            raise ValidationError(
                {
                    "telegram_chat_id": (
                        "Для канала укажите числовой chat ID или @username."
                    )
                }
            )

    def save(self, *args: object, **kwargs: object) -> None:
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.get_target_type_display()}: {self.telegram_chat_id}"


class Delivery(models.Model):
    """One delivery attempt stream for an analysis-target pair."""

    analysis = models.ForeignKey(
        Analysis,
        verbose_name="Анализ",
        on_delete=models.PROTECT,
        related_name="deliveries",
    )
    target = models.ForeignKey(
        DeliveryTarget,
        verbose_name="Получатель",
        on_delete=models.PROTECT,
        related_name="deliveries",
    )
    status = models.CharField(
        "Статус",
        max_length=16,
        choices=DeliveryStatus.choices,
        default=DeliveryStatus.PENDING,
    )
    telegram_message_id = models.CharField(
        "Telegram message ID",
        max_length=64,
        blank=True,
    )
    attempts = models.PositiveIntegerField("Попыток", default=0)
    sent_at = models.DateTimeField("Отправлено", null=True, blank=True)
    last_error = models.TextField("Последняя ошибка", blank=True)

    class Meta:
        verbose_name = "Доставка Telegram"
        verbose_name_plural = "Доставки Telegram"
        ordering = ("-sent_at", "-pk")
        constraints = [
            models.UniqueConstraint(
                fields=("analysis", "target"),
                name="telegram_delivery_analysis_target_uniq",
            )
        ]
        indexes = [
            models.Index(
                fields=("status",),
                name="telegram_delivery_status_idx",
            )
        ]

    def __str__(self) -> str:
        return f"Анализ {self.analysis_id} → {self.target.telegram_chat_id}"
