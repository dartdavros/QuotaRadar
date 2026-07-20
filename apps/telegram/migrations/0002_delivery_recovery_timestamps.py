import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("telegram", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="delivery",
            name="created_at",
            field=models.DateTimeField(
                auto_now_add=True,
                default=django.utils.timezone.now,
                verbose_name="Создана",
            ),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="delivery",
            name="last_attempt_at",
            field=models.DateTimeField(
                blank=True,
                null=True,
                verbose_name="Последняя попытка",
            ),
        ),
        migrations.AddField(
            model_name="delivery",
            name="next_attempt_at",
            field=models.DateTimeField(
                blank=True,
                null=True,
                verbose_name="Следующая попытка не раньше",
            ),
        ),
        migrations.AddField(
            model_name="delivery",
            name="updated_at",
            field=models.DateTimeField(
                auto_now=True,
                default=django.utils.timezone.now,
                verbose_name="Изменена",
            ),
            preserve_default=False,
        ),
        migrations.AlterModelOptions(
            name="delivery",
            options={
                "ordering": ("-created_at", "-pk"),
                "verbose_name": "Доставка Telegram",
                "verbose_name_plural": "Доставки Telegram",
            },
        ),
    ]
