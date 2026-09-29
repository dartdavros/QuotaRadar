"""Campaigns and immutable delivery assignments; no live counters to drift."""
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models, transaction
from django.db.models import Q

from apps.sources.models import Feed
from apps.telegram.models import DeliveryTarget, DeliveryTargetType
from .formatting import campaign_copy, utf16_length, validate_body, validate_copy


class PlacementStatus(models.TextChoices):
    RESERVED = "reserved", "Зарезервировано"
    SENDING = "sending", "Отправляется"
    UNCERTAIN = "uncertain", "Требуется проверка канала"
    SENT = "sent", "Опубликовано"
    RELEASED = "released", "Не опубликовано"


HELD_STATUSES = (PlacementStatus.RESERVED, PlacementStatus.SENDING, PlacementStatus.UNCERTAIN)


class Campaign(models.Model):
    target = models.ForeignKey("telegram.DeliveryTarget", verbose_name="Канал", on_delete=models.PROTECT)
    body = models.TextField("Текст рекомендации", blank=True)
    message = models.TextField("Текст рекламы", blank=True)
    link_label = models.CharField("Текст ссылки", max_length=200, blank=True)
    url = models.URLField("URL", max_length=2000, blank=True)
    total_posts = models.PositiveIntegerField("Количество постов", validators=[MinValueValidator(1)])
    enabled = models.BooleanField("Активна", default=False)
    created_at = models.DateTimeField("Создана", auto_now_add=True)

    class Meta:
        verbose_name = "Рекламная кампания"
        verbose_name_plural = "Рекламные кампании"
        ordering = ("-created_at", "-pk")
        constraints = [
            models.UniqueConstraint(fields=("target",), condition=Q(enabled=True), name="advertising_one_active_target"),
            models.CheckConstraint(condition=Q(total_posts__gte=1), name="advertising_positive_total"),
        ]

    @property
    def block_length(self):
        return utf16_length(campaign_copy(self)[0])

    @property
    def sent_posts(self):
        return self.placements.filter(status=PlacementStatus.SENT).count() if self.pk else 0

    @property
    def reserved_posts(self):
        return self.placements.filter(status__in=HELD_STATUSES).count() if self.pk else 0

    @property
    def remaining_posts(self):
        return max(0, self.total_posts - self.sent_posts) if self.total_posts else 0

    def clean(self):
        super().clean()
        self.body = self.body.replace("\r\n", "\n").strip()
        self.message, self.link_label, self.url = self.message.strip(), self.link_label.strip(), self.url.strip()
        if self.body:
            try:
                validate_body(self.body)
            except ValidationError as exc:
                raise ValidationError({"body": exc.messages}) from None
        else:
            validate_copy(self.message, self.link_label, self.url)
        if self.target_id and (self.target.target_type != DeliveryTargetType.CHANNEL or self.target.feed != Feed.QUOTA):
            raise ValidationError({"target": "Реклама доступна только для канала квот QuotaRadar."})
        if self.pk:
            original_target = type(self).objects.filter(pk=self.pk).values_list("target_id", flat=True).first()
            if original_target != self.target_id:
                raise ValidationError({"target": "Канал сохранённой кампании менять нельзя."})
            if self.total_posts is not None and self.total_posts < self.sent_posts + self.reserved_posts:
                raise ValidationError({"total_posts": "Количество меньше уже опубликованных и зарезервированных размещений."})
            if self.enabled and self.remaining_posts == 0:
                raise ValidationError({"enabled": "Кампания завершена. Увеличьте количество постов перед включением."})

    def save(self, *args, **kwargs):
        with transaction.atomic():
            if self.target_id:
                DeliveryTarget.objects.select_for_update().get(pk=self.target_id)
            self.full_clean()
            super().save(*args, **kwargs)

    def __str__(self):
        return f"{(self.body or self.message)[:60]} ({self.target})"


class Placement(models.Model):
    campaign = models.ForeignKey(Campaign, verbose_name="Кампания", on_delete=models.PROTECT, related_name="placements")
    delivery = models.OneToOneField("telegram.Delivery", verbose_name="Доставка", on_delete=models.PROTECT, related_name="advertising")
    status = models.CharField("Статус", max_length=16, choices=PlacementStatus.choices, default=PlacementStatus.RESERVED)
    created_at = models.DateTimeField("Зарезервировано", auto_now_add=True)
    sent_at = models.DateTimeField("Опубликовано", null=True, blank=True)
    resolution_note = models.TextField("Результат проверки канала", blank=True)
    telegram_message_id = models.CharField("Telegram message ID найденного поста", max_length=64, blank=True)

    class Meta:
        verbose_name = "Рекламное размещение"
        verbose_name_plural = "Рекламные размещения"
        ordering = ("-created_at", "-pk")

    def __str__(self):
        return f"Кампания {self.campaign_id}, доставка {self.delivery_id}"
