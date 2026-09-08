"""X source and ingested post models."""

from __future__ import annotations

import re
from django.core.exceptions import ValidationError
from django.db import models


class SourceProvider(models.TextChoices):
    OPENAI = "openai", "OpenAI"
    ANTHROPIC = "anthropic", "Anthropic"
    CURSOR = "cursor", "Cursor"
    GOOGLE = "google", "Google"


class Feed(models.TextChoices):
    QUOTA = "quota", "Квоты"
    NEWS = "news", "Новости"


class Source(models.Model):
    """Trusted X account monitored by QuotaRadar."""

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


class SourceSubscription(models.Model):
    """Independent editorial membership; Source.enabled controls collection."""

    source = models.ForeignKey(Source, on_delete=models.CASCADE, related_name="subscriptions")
    feed = models.CharField("Направление", max_length=16, choices=Feed.choices)
    enabled = models.BooleanField("Активна", default=False)
    priority = models.BooleanField("Приоритетный источник", default=False)
    query_terms = models.CharField("Тематический фильтр X", max_length=300, blank=True)

    class Meta:
        verbose_name = "Подписка на источник"
        verbose_name_plural = "Подписки на источники"
        constraints = [models.UniqueConstraint(fields=("source", "feed"), name="source_feed_unique")]

    def clean(self):
        super().clean()
        if self.query_terms and not re.fullmatch(r"[A-Za-z0-9_ -]+", self.query_terms):
            raise ValidationError({"query_terms": "Используйте слова через пробел без операторов X."})
        if self.feed == Feed.NEWS and self.source_id and not re.fullmatch(r"[A-Za-z0-9_]{1,15}", self.source.username):
            raise ValidationError({"source": "Некорректное имя аккаунта X."})

    def __str__(self):
        return f"{self.source} / {self.get_feed_display()}"


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
