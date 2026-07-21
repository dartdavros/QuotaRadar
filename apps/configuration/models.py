"""Database-backed runtime configuration models."""

from __future__ import annotations

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models


class PromptTemplate(models.Model):
    """Versioned prompt used to classify source publications."""

    code = models.CharField("Код", max_length=100)
    version = models.PositiveIntegerField("Версия")
    system_prompt = models.TextField("Системный промпт")
    user_prompt_template = models.TextField("Шаблон пользовательского промпта")
    is_active = models.BooleanField("Активен", default=True)
    created_at = models.DateTimeField("Создан", auto_now_add=True)

    class Meta:
        verbose_name = "Шаблон промпта"
        verbose_name_plural = "Шаблоны промптов"
        ordering = ("code", "-version")
        constraints = [
            models.UniqueConstraint(
                fields=("code", "version"),
                name="configuration_prompt_code_version_uniq",
            ),
        ]

    def clean(self) -> None:
        super().clean()
        if self.pk and not self.is_active and self.system_configurations.exists():
            raise ValidationError(
                {
                    "is_active": "Нельзя отключить промпт, выбранный системной конфигурацией."
                }
            )

    def save(self, *args: object, **kwargs: object) -> None:
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.code} v{self.version}"


class SystemConfiguration(models.Model):
    """Singleton containing the active runtime configuration."""

    SINGLETON_PK = 1

    monitoring_enabled = models.BooleanField("Мониторинг включён", default=False)
    poll_interval_seconds = models.PositiveIntegerField(
        "Интервал опроса, сек.",
        default=300,
        validators=(MinValueValidator(1),),
    )
    bootstrap_post_limit = models.PositiveIntegerField(
        "Постов при первом опросе",
        default=10,
        validators=(MinValueValidator(5), MaxValueValidator(100)),
        help_text=(
            "Количество последних постов в единственной странице первого опроса "
            "источника. Допустимо от 5 до 100."
        ),
    )
    regular_poll_post_limit = models.PositiveIntegerField(
        "Постов на страницу регулярного опроса",
        default=5,
        validators=(MinValueValidator(5), MaxValueValidator(100)),
        help_text=(
            "Размер страницы X API при последующих опросах. Если новых постов "
            "больше, система продолжает пагинацию. Допустимо от 5 до 100."
        ),
    )
    llm_provider = models.CharField("Код ИИ-провайдера", max_length=100, blank=True)
    llm_base_url = models.URLField("Базовый URL ИИ-провайдера", blank=True)
    llm_model = models.CharField("Модель", max_length=200, blank=True)
    llm_temperature = models.DecimalField(
        "Температура",
        max_digits=4,
        decimal_places=3,
        default=Decimal("0.000"),
        validators=(MinValueValidator(Decimal("0")), MaxValueValidator(Decimal("2"))),
    )
    llm_max_tokens = models.PositiveIntegerField(
        "Максимум токенов ответа",
        default=1000,
        validators=(MinValueValidator(1),),
    )
    llm_timeout_seconds = models.PositiveIntegerField(
        "Таймаут ИИ-запроса, сек.",
        default=30,
        validators=(MinValueValidator(1),),
    )
    retry_count = models.PositiveIntegerField(
        "Количество повторов",
        default=3,
    )
    active_prompt = models.ForeignKey(
        PromptTemplate,
        verbose_name="Активный промпт",
        on_delete=models.PROTECT,
        related_name="system_configurations",
    )

    class Meta:
        verbose_name = "Системная конфигурация"
        verbose_name_plural = "Системная конфигурация"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(id=1),
                name="configuration_system_singleton_pk",
            )
        ]

    def clean(self) -> None:
        super().clean()
        if self.pk not in (None, self.SINGLETON_PK):
            raise ValidationError("Допускается только одна системная конфигурация.")
        if self.active_prompt_id and not self.active_prompt.is_active:
            raise ValidationError(
                {"active_prompt": "Выбранный шаблон промпта должен быть активен."}
            )

    def save(self, *args: object, **kwargs: object) -> None:
        if self.pk is None:
            self.pk = self.SINGLETON_PK
        elif self.pk != self.SINGLETON_PK:
            raise ValidationError("Допускается только одна системная конфигурация.")
        if (
            self._state.adding
            and type(self).objects.filter(pk=self.SINGLETON_PK).exists()
        ):
            raise ValidationError("Системная конфигурация уже существует.")
        self.full_clean()
        super().save(*args, **kwargs)

    @classmethod
    def load(cls) -> "SystemConfiguration":
        """Return the singleton configuration or raise the model DoesNotExist."""

        return cls.objects.select_related("active_prompt").get(pk=cls.SINGLETON_PK)

    def __str__(self) -> str:
        return "Системная конфигурация QuotaRadar"
