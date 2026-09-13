"""Explicit opt-in settings for the independent news channel."""

from decimal import Decimal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone

from apps.sources.models import Feed


def default_windows():
    return [720, 1140, 1290]


class NewsConfiguration(models.Model):
    collection_enabled = models.BooleanField("Сбор новостей включён", default=False)
    analysis_enabled = models.BooleanField("Анализ новостей включён", default=False)
    publishing_enabled = models.BooleanField("Публикация новостей включена", default=False)
    activated_at = models.DateTimeField("Начало новостного потока", null=True, blank=True)
    target = models.ForeignKey("telegram.DeliveryTarget", verbose_name="Новостной канал",
                              on_delete=models.PROTECT, null=True, blank=True)
    timezone = models.CharField("Часовой пояс публикаций", max_length=64, default="Europe/Moscow")
    windows = models.JSONField("Окна публикаций (минуты с начала суток)", default=default_windows)
    daily_limit = models.PositiveSmallIntegerField("Максимум публикаций в сутки", default=3,
        validators=[MinValueValidator(1), MaxValueValidator(3)])
    min_score = models.PositiveSmallIntegerField("Минимальная оценка", default=70,
        validators=[MinValueValidator(0), MaxValueValidator(100)])
    expiry_hours = models.PositiveSmallIntegerField("Актуальность новости, часов", default=36,
        validators=[MinValueValidator(1), MaxValueValidator(168)])
    weekly_x_limit = models.DecimalField("Недельный бюджет новых X-запросов, USD",
        max_digits=6, decimal_places=3, default=Decimal("3.000"),
        validators=[MinValueValidator(Decimal("0.100")), MaxValueValidator(Decimal("10.000"))])
    llm_model = models.CharField("Модель ИИ (пусто — системная)", max_length=200, blank=True)
    assessment_prompt = models.ForeignKey("configuration.PromptTemplate", on_delete=models.PROTECT,
        related_name="news_assessment_configurations", verbose_name="Промпт отбора", null=True, blank=True)
    writing_prompt = models.ForeignKey("configuration.PromptTemplate", on_delete=models.PROTECT,
        related_name="news_writing_configurations", verbose_name="Промпт редактора", null=True, blank=True)
    verification_prompt = models.ForeignKey("configuration.PromptTemplate", on_delete=models.PROTECT,
        related_name="news_verification_configurations", verbose_name="Промпт проверки", null=True, blank=True)

    class Meta:
        verbose_name = "Настройки новостей"
        verbose_name_plural = "Настройки новостей"
        constraints = [models.CheckConstraint(condition=models.Q(id=1), name="news_config_singleton")]

    def clean(self):
        super().clean()
        try:
            ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, ValueError, TypeError):
            raise ValidationError({"timezone": "Укажите корректный часовой пояс IANA."}) from None
        if (not isinstance(self.windows, list) or not self.windows or len(self.windows) > 3
                or any(type(w) is not int or not 0 <= w < 1440 for w in self.windows)
                or len(set(self.windows)) != len(self.windows)):
            raise ValidationError({"windows": "Задайте до трёх разных минут суток: [720, 1140, 1290]."})
        if self.target_id and (self.target.feed != Feed.NEWS or self.target.target_type != "channel"):
            raise ValidationError({"target": "Выберите канал направления «Новости»."})
        if self.publishing_enabled and (not self.target_id or not self.target.enabled):
            raise ValidationError({"target": "Для публикации нужен активный новостной канал."})
        if self.analysis_enabled or self.publishing_enabled:
            for field in ("assessment_prompt", "writing_prompt", "verification_prompt"):
                prompt = getattr(self, field)
                if prompt is None or not prompt.is_active or "{data}" not in prompt.user_prompt_template:
                    raise ValidationError({field: "Выберите активный промпт с {data} в пользовательском шаблоне."})

    def save(self, *args, **kwargs):
        if self._state.adding and type(self).objects.filter(pk=1).exists():
            raise ValidationError("Настройки новостей уже существуют.")
        self.pk = self.pk or 1
        if self.collection_enabled and self.activated_at is None:
            self.activated_at = timezone.now()
        self.full_clean()
        return super().save(*args, **kwargs)

    @classmethod
    def load(cls):
        return cls.objects.select_related("target", "assessment_prompt", "writing_prompt", "verification_prompt").get(pk=1)

    def __str__(self):
        return "Настройки новостей"
