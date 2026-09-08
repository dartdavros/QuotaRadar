"""Bounded X collection and conservative additional-spend accounting."""

from django.db import models


class CollectionCheckpoint(models.Model):
    source = models.OneToOneField("sources.Source", on_delete=models.PROTECT)
    query_hash = models.CharField(max_length=64, blank=True)
    completed_until = models.DateTimeField(null=True, blank=True)
    window_start = models.DateTimeField(null=True, blank=True)
    window_end = models.DateTimeField(null=True, blank=True)
    next_token = models.TextField(blank=True)
    next_attempt_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField("Ошибка / пропуск", blank=True)


class XBudgetPeriod(models.Model):
    week = models.DateField(unique=True)
    limit = models.DecimalField(max_digits=8, decimal_places=3)
    committed = models.DecimalField(max_digits=8, decimal_places=3, default=0)

    class Meta:
        verbose_name = "Бюджет X за неделю"
        verbose_name_plural = "Бюджеты X по неделям"


class XApiUsage(models.Model):
    period = models.ForeignKey(XBudgetPeriod, on_delete=models.PROTECT)
    source = models.ForeignKey("sources.Source", on_delete=models.PROTECT)
    initial_fill = models.ForeignKey("news.InitialFill", on_delete=models.PROTECT, null=True, blank=True)
    operation = models.CharField(max_length=32)
    reserved = models.DecimalField(max_digits=8, decimal_places=3)
    charged_estimate = models.DecimalField(max_digits=8, decimal_places=3, null=True)
    status = models.CharField(max_length=16, default="reserved")
    resources = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Расход X"
        verbose_name_plural = "Расходы X"
