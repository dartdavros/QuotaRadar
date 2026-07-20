from decimal import Decimal

import django.core.validators
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="PromptTemplate",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("code", models.CharField(max_length=100, verbose_name="Код")),
                ("version", models.PositiveIntegerField(verbose_name="Версия")),
                ("system_prompt", models.TextField(verbose_name="Системный промпт")),
                (
                    "user_prompt_template",
                    models.TextField(verbose_name="Шаблон пользовательского промпта"),
                ),
                (
                    "is_active",
                    models.BooleanField(default=True, verbose_name="Активен"),
                ),
                (
                    "created_at",
                    models.DateTimeField(auto_now_add=True, verbose_name="Создан"),
                ),
            ],
            options={
                "verbose_name": "Шаблон промпта",
                "verbose_name_plural": "Шаблоны промптов",
                "ordering": ("code", "-version"),
            },
        ),
        migrations.CreateModel(
            name="SystemConfiguration",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "monitoring_enabled",
                    models.BooleanField(
                        default=False, verbose_name="Мониторинг включён"
                    ),
                ),
                (
                    "poll_interval_seconds",
                    models.PositiveIntegerField(
                        default=300,
                        validators=[django.core.validators.MinValueValidator(1)],
                        verbose_name="Интервал опроса, сек.",
                    ),
                ),
                (
                    "llm_provider",
                    models.CharField(
                        blank=True, max_length=100, verbose_name="Код ИИ-провайдера"
                    ),
                ),
                (
                    "llm_base_url",
                    models.URLField(
                        blank=True, verbose_name="Базовый URL ИИ-провайдера"
                    ),
                ),
                (
                    "llm_model",
                    models.CharField(blank=True, max_length=200, verbose_name="Модель"),
                ),
                (
                    "llm_temperature",
                    models.DecimalField(
                        decimal_places=3,
                        default=Decimal("0.000"),
                        max_digits=4,
                        validators=[
                            django.core.validators.MinValueValidator(Decimal("0")),
                            django.core.validators.MaxValueValidator(Decimal("2")),
                        ],
                        verbose_name="Температура",
                    ),
                ),
                (
                    "llm_max_tokens",
                    models.PositiveIntegerField(
                        default=1000,
                        validators=[django.core.validators.MinValueValidator(1)],
                        verbose_name="Максимум токенов ответа",
                    ),
                ),
                (
                    "llm_timeout_seconds",
                    models.PositiveIntegerField(
                        default=30,
                        validators=[django.core.validators.MinValueValidator(1)],
                        verbose_name="Таймаут ИИ-запроса, сек.",
                    ),
                ),
                (
                    "retry_count",
                    models.PositiveIntegerField(
                        default=3, verbose_name="Количество повторов"
                    ),
                ),
                (
                    "active_prompt",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="system_configurations",
                        to="configuration.prompttemplate",
                        verbose_name="Активный промпт",
                    ),
                ),
            ],
            options={
                "verbose_name": "Системная конфигурация",
                "verbose_name_plural": "Системная конфигурация",
            },
        ),
        migrations.AddConstraint(
            model_name="prompttemplate",
            constraint=models.UniqueConstraint(
                fields=("code", "version"),
                name="configuration_prompt_code_version_uniq",
            ),
        ),
        migrations.AddConstraint(
            model_name="systemconfiguration",
            constraint=models.CheckConstraint(
                condition=models.Q(("id", 1)), name="configuration_system_singleton_pk"
            ),
        ),
    ]
