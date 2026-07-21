"""Operational monitoring events shown in Django Admin."""

from __future__ import annotations

from django.db import models

from apps.sources.models import Source


class MonitoringComponent(models.TextChoices):
    X = "x", "X"
    AI = "ai", "ИИ"
    TELEGRAM = "telegram", "Telegram"
    SYSTEM = "system", "Система"


class MonitoringEventStatus(models.TextChoices):
    SUCCESS = "success", "Успех"
    ERROR = "error", "Ошибка"


class MonitoringEvent(models.Model):
    """One significant operational result from the processing pipeline."""

    created_at = models.DateTimeField("Время", auto_now_add=True, db_index=True)
    component = models.CharField(
        "Компонент",
        max_length=16,
        choices=MonitoringComponent.choices,
        db_index=True,
    )
    status = models.CharField(
        "Статус",
        max_length=16,
        choices=MonitoringEventStatus.choices,
        db_index=True,
    )
    source = models.ForeignKey(
        Source,
        verbose_name="Источник",
        on_delete=models.SET_NULL,
        related_name="monitoring_events",
        null=True,
        blank=True,
    )
    message = models.TextField("Сообщение")
    error_type = models.CharField("Тип ошибки", max_length=255, blank=True)
    task_id = models.CharField("Celery Task ID", max_length=255, blank=True)

    class Meta:
        verbose_name = "Событие мониторинга"
        verbose_name_plural = "События мониторинга"
        ordering = ("-created_at", "-pk")

    def __str__(self) -> str:
        return f"{self.get_component_display()}: {self.get_status_display()}"
