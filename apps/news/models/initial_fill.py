"""One budgeted historical fill per real target, independent of process restarts."""
from decimal import Decimal
from django.db import models

class InitialFill(models.Model):
    target = models.OneToOneField("telegram.DeliveryTarget", on_delete=models.PROTECT)
    status = models.CharField("Статус", max_length=20, default="archive",
        choices=[(s, label) for s, label in (
            ("archive", "Проверка архива"), ("collecting", "Чтение истории"), ("assessing", "Отбор"),
            ("publishing", "Публикация"), ("completed", "Завершено"), ("blocked", "Остановлено"))])
    window_start = models.DateTimeField("История с")
    window_end = models.DateTimeField("История до")
    started_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField("Завершить до")
    committed = models.DecimalField("Расход и резерв X, USD", max_digits=8, decimal_places=3, default=Decimal("0"))
    lease_until = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField("Причина / ошибка", blank=True)

    class Meta:
        verbose_name = "Первичное наполнение"
        verbose_name_plural = "Первичное наполнение"

class InitialFillSource(models.Model):
    run = models.ForeignKey(InitialFill, on_delete=models.CASCADE, related_name="sources")
    subscription = models.ForeignKey("sources.SourceSubscription", on_delete=models.PROTECT)
    query_terms = models.CharField(max_length=300, blank=True)
    next_token = models.TextField(blank=True)
    done = models.BooleanField(default=False)
    attempts = models.PositiveSmallIntegerField(default=0)
    checked_at = models.DateTimeField(null=True, blank=True)
    next_attempt_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=("run", "subscription"), name="news_fill_source_unique")]

class InitialFillAssessment(models.Model):
    run = models.ForeignKey(InitialFill, on_delete=models.CASCADE, related_name="assessments")
    assessment = models.ForeignKey("news.NewsAssessment", on_delete=models.PROTECT)

    class Meta:
        constraints = [models.UniqueConstraint(fields=("run", "assessment"), name="news_fill_assessment_unique")]
