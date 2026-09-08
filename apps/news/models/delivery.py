"""Frozen news publications, media and delivery receipts."""

from django.db import models


class PublicationStatus(models.TextChoices):
    PREPARING = "preparing", "Подготавливается"
    READY = "ready", "Подготовлена"
    SENDING = "sending", "Отправляется"
    SENT = "sent", "Отправлена"
    UNCERTAIN = "uncertain", "Результат отправки неизвестен"
    BLOCKED = "blocked", "Заблокирована"


class NewsPublication(models.Model):
    event = models.ForeignKey("news.NewsEvent", on_delete=models.PROTECT, related_name="publications")
    target = models.ForeignKey("telegram.DeliveryTarget", on_delete=models.PROTECT)
    status = models.CharField("Статус", max_length=16, choices=PublicationStatus.choices, default=PublicationStatus.PREPARING)
    initial_fill = models.ForeignKey("news.InitialFill", on_delete=models.PROTECT, null=True, blank=True, related_name="publications")
    upload_media = models.BooleanField(default=False)
    media_attempts = models.PositiveSmallIntegerField(default=0)
    title = models.CharField("Заголовок", max_length=160, blank=True)
    text = models.TextField("Текст", blank=True)
    rendered = models.TextField(blank=True)
    payload_hash = models.CharField(max_length=64, blank=True)
    prompt_versions = models.JSONField(default=dict, blank=True)
    source_ids = models.JSONField(default=list, blank=True)
    model = models.CharField(max_length=200, blank=True)
    usage = models.JSONField(default=dict, blank=True)
    slot_date = models.DateField(null=True, blank=True)
    slot_minute = models.PositiveSmallIntegerField(null=True, blank=True)
    urgent = models.BooleanField(default=False)
    attempts = models.PositiveSmallIntegerField(default=0)
    lease_until = models.DateTimeField(null=True, blank=True)
    next_attempt_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField("Причина / ошибка", blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Новостная публикация"
        verbose_name_plural = "Новостные публикации"
        constraints = [models.UniqueConstraint(fields=("event", "target"), name="news_event_target_unique")]

    def __str__(self):
        return self.title or f"Публикация {self.pk}"


class NewsDailyQuota(models.Model):
    target = models.ForeignKey("telegram.DeliveryTarget", on_delete=models.PROTECT)
    date = models.DateField()

    class Meta:
        constraints = [models.UniqueConstraint(fields=("target", "date"), name="news_target_day_unique")]


class NewsDelivery(models.Model):
    publication = models.OneToOneField(NewsPublication, on_delete=models.PROTECT, related_name="delivery")
    message_ids = models.JSONField(default=list, blank=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    sent_at = models.DateTimeField(null=True, blank=True)
    next_attempt_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True)
    resolution_note = models.TextField("Результат проверки канала оператором", blank=True)

    class Meta:
        verbose_name = "Новостная доставка"
        verbose_name_plural = "Новостные доставки"


class MediaAsset(models.Model):
    publication = models.ForeignKey(NewsPublication, on_delete=models.CASCADE, related_name="media")
    post = models.ForeignKey("sources.SourcePost", on_delete=models.PROTECT)
    media_key = models.CharField(max_length=100)
    kind = models.CharField(max_length=20)
    position = models.PositiveSmallIntegerField()
    url = models.URLField(max_length=2000)
    file = models.FileField(upload_to="news", blank=True)
    checksum = models.CharField(max_length=64, blank=True)
    size = models.PositiveBigIntegerField(default=0)
    telegram_file_id = models.TextField(blank=True)
    telegram_bot_identity = models.CharField(max_length=32, blank=True)

    class Meta:
        ordering = ("position", "pk")
        constraints = [models.UniqueConstraint(fields=("publication", "media_key"), name="news_publication_media_unique")]
