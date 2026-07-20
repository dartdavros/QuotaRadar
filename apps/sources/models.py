"""X source and ingested post models."""

from __future__ import annotations

from django.db import models


class SourceProvider(models.TextChoices):
    OPENAI = "openai", "OpenAI"
    ANTHROPIC = "anthropic", "Anthropic"


class Source(models.Model):
    """Official X account monitored by QuotaRadar."""

    provider = models.CharField(
        "Провайдер",
        max_length=32,
        choices=SourceProvider.choices,
    )
    username = models.CharField("Имя пользователя X", max_length=100, unique=True)
    x_user_id = models.CharField("X User ID", max_length=64, blank=True)
    enabled = models.BooleanField("Активен", default=True)
    last_post_id = models.CharField("Последний Post ID", max_length=64, blank=True)
    last_checked_at = models.DateTimeField("Последняя проверка", null=True, blank=True)
    last_success_at = models.DateTimeField("Последний успех", null=True, blank=True)
    last_error = models.TextField("Последняя ошибка", blank=True)

    class Meta:
        verbose_name = "Источник"
        verbose_name_plural = "Источники"
        ordering = ("provider", "username")

    def __str__(self) -> str:
        return f"@{self.username}"


class SourcePostProcessingStatus(models.TextChoices):
    RECEIVED = "received", "Получен"
    QUEUED = "queued", "Поставлен в очередь"
    ANALYZED_IRRELEVANT = "analyzed_irrelevant", "Проанализирован: нерелевантен"
    ANALYZED_RELEVANT = "analyzed_relevant", "Проанализирован: релевантен"
    FAILED = "failed", "Ошибка"


class SourcePost(models.Model):
    """One immutable publication received from the X API."""

    source = models.ForeignKey(
        Source,
        verbose_name="Источник",
        on_delete=models.PROTECT,
        related_name="posts",
    )
    external_id = models.CharField("X Post ID", max_length=64, unique=True)
    text = models.TextField("Текст")
    normalized_text = models.TextField("Нормализованный текст")
    source_url = models.URLField("Ссылка на источник", max_length=500)
    published_at = models.DateTimeField("Опубликован")
    received_at = models.DateTimeField("Получен", auto_now_add=True)
    raw_data = models.JSONField("Raw response")
    processing_status = models.CharField(
        "Статус обработки",
        max_length=32,
        choices=SourcePostProcessingStatus.choices,
        default=SourcePostProcessingStatus.RECEIVED,
    )
    processing_started_at = models.DateTimeField(
        "Обработка начата",
        null=True,
        blank=True,
    )
    last_error = models.TextField("Последняя ошибка", blank=True)

    class Meta:
        verbose_name = "Пост источника"
        verbose_name_plural = "Посты источников"
        ordering = ("-published_at", "-external_id")
        indexes = [
            models.Index(
                fields=("source", "published_at"),
                name="sources_post_source_pub_idx",
            ),
            models.Index(
                fields=("processing_status",),
                name="sources_post_status_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"@{self.source.username}: {self.external_id}"
