"""Facts and event identities are independent of the quota Analysis model."""

from django.db import models


class WorkStatus(models.TextChoices):
    PENDING = "pending", "Ожидает"
    RUNNING = "running", "Обрабатывается"
    DONE = "done", "Завершён"
    BLOCKED = "blocked", "Заблокирован"


class NewsAssessment(models.Model):
    post = models.OneToOneField("sources.SourcePost", on_delete=models.PROTECT, related_name="news_assessment")
    status = models.CharField("Статус", max_length=16, choices=WorkStatus.choices, default=WorkStatus.PENDING)
    attempts = models.PositiveSmallIntegerField(default=0)
    lease_until = models.DateTimeField(null=True, blank=True)
    next_attempt_at = models.DateTimeField(null=True, blank=True)
    result = models.JSONField(default=dict, blank=True)
    model = models.CharField(max_length=200, blank=True)
    prompt_version = models.PositiveIntegerField(default=0)
    usage = models.JSONField(default=dict, blank=True)
    last_error = models.TextField("Причина / ошибка", blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Отбор новости"
        verbose_name_plural = "Отбор новостей"
        indexes = [models.Index(fields=("status", "next_attempt_at"), name="news_assessment_queue")]

    def __str__(self):
        return f"Отбор {self.post_id}"


class NewsEvent(models.Model):
    fingerprint = models.CharField(max_length=64, unique=True)
    product = models.CharField("Продукт", max_length=120)
    version = models.CharField("Версия / функция", max_length=180, blank=True)
    event_type = models.CharField("Тип события", max_length=32)
    score = models.PositiveSmallIntegerField("Оценка")
    urgent = models.BooleanField("Срочная", default=False)
    facts = models.JSONField(default=list)
    first_seen_at = models.DateTimeField()
    last_seen_at = models.DateTimeField()
    expires_at = models.DateTimeField()
    last_error = models.TextField("Причина / ошибка", blank=True)

    class Meta:
        verbose_name = "Новостное событие"
        verbose_name_plural = "Новостные события"
        indexes = [models.Index(fields=("expires_at", "score"), name="news_event_selection")]

    def __str__(self):
        return f"{self.product}: {self.version or self.event_type}"


class NewsEventEvidence(models.Model):
    event = models.ForeignKey(NewsEvent, on_delete=models.CASCADE, related_name="evidence")
    post = models.ForeignKey("sources.SourcePost", on_delete=models.PROTECT)
    facts = models.JSONField(default=list)

    class Meta:
        constraints = [models.UniqueConstraint(fields=("event", "post"), name="news_event_post_unique")]
