from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("sources", "0003_sourcepost_processing_started_at"),
    ]

    operations = [
        migrations.CreateModel(
            name="MonitoringEvent",
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
                    "created_at",
                    models.DateTimeField(
                        auto_now_add=True,
                        db_index=True,
                        verbose_name="Время",
                    ),
                ),
                (
                    "component",
                    models.CharField(
                        choices=[
                            ("x", "X"),
                            ("ai", "ИИ"),
                            ("telegram", "Telegram"),
                            ("system", "Система"),
                        ],
                        db_index=True,
                        max_length=16,
                        verbose_name="Компонент",
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[("success", "Успех"), ("error", "Ошибка")],
                        db_index=True,
                        max_length=16,
                        verbose_name="Статус",
                    ),
                ),
                ("message", models.TextField(verbose_name="Сообщение")),
                (
                    "error_type",
                    models.CharField(
                        blank=True,
                        max_length=255,
                        verbose_name="Тип ошибки",
                    ),
                ),
                (
                    "task_id",
                    models.CharField(
                        blank=True,
                        max_length=255,
                        verbose_name="Celery Task ID",
                    ),
                ),
                (
                    "source",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="monitoring_events",
                        to="sources.source",
                        verbose_name="Источник",
                    ),
                ),
            ],
            options={
                "verbose_name": "Событие мониторинга",
                "verbose_name_plural": "События мониторинга",
                "ordering": ("-created_at", "-pk"),
            },
        ),
    ]
