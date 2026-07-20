"""Validated LLM analysis results for ingested X publications."""

from __future__ import annotations

from django.core.exceptions import ValidationError
from django.db import models

from apps.sources.models import SourcePost, SourceProvider


class AnalysisEventType(models.TextChoices):
    QUOTA_RESET = "quota_reset", "Сброс квоты"
    QUOTA_INCREASE = "quota_increase", "Повышение квоты"
    QUOTA_EXTENSION = "quota_extension", "Продление повышенной квоты"


class AnalysisProduct(models.TextChoices):
    CODEX = "codex", "Codex"
    CLAUDE_CODE = "claude_code", "Claude Code"


class Analysis(models.Model):
    """One persisted analysis attempt/result for one immutable source post."""

    source_post = models.OneToOneField(
        SourcePost,
        verbose_name="Пост источника",
        on_delete=models.CASCADE,
        related_name="analysis",
    )
    is_relevant = models.BooleanField(
        "Релевантен",
        null=True,
        blank=True,
        help_text="Не задано, если анализ завершился ошибкой.",
    )
    event_type = models.CharField(
        "Тип события",
        max_length=32,
        choices=AnalysisEventType.choices,
        blank=True,
    )
    provider = models.CharField(
        "Провайдер",
        max_length=32,
        choices=SourceProvider.choices,
    )
    product = models.CharField(
        "Продукт",
        max_length=32,
        choices=AnalysisProduct.choices,
    )
    title_ru = models.CharField("Заголовок на русском", max_length=255, blank=True)
    message_ru = models.TextField("Сообщение на русском", blank=True)
    model = models.CharField("Модель", max_length=200)
    prompt_version = models.PositiveIntegerField("Версия промпта")
    raw_response = models.JSONField("Raw response", null=True, blank=True)
    error = models.TextField("Ошибка анализа", blank=True)
    created_at = models.DateTimeField("Создан", auto_now_add=True)
    updated_at = models.DateTimeField("Изменён", auto_now=True)

    class Meta:
        verbose_name = "Анализ"
        verbose_name_plural = "Анализы"
        ordering = ("-created_at",)

    @property
    def is_successful(self) -> bool:
        return self.is_relevant is not None and not self.error

    def clean(self) -> None:
        super().clean()
        if self.is_relevant is True:
            errors: dict[str, str] = {}
            if not self.event_type:
                errors["event_type"] = "Для релевантного события нужен тип события."
            if not self.title_ru.strip():
                errors["title_ru"] = "Для релевантного события нужен заголовок."
            if not self.message_ru.strip():
                errors["message_ru"] = "Для релевантного события нужен текст."
            if errors:
                raise ValidationError(errors)
        elif self.is_relevant is False and any(
            (self.event_type, self.title_ru.strip(), self.message_ru.strip())
        ):
            raise ValidationError(
                "Нерелевантный анализ не должен содержать событие или сообщение."
            )
        elif self.is_relevant is None and not self.error.strip():
            raise ValidationError(
                {"error": "Для неуспешного анализа необходимо сохранить ошибку."}
            )

    def __str__(self) -> str:
        return f"Анализ X Post {self.source_post.external_id}"
