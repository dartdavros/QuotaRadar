from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("analysis", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="analysis",
            name="delivery_fanout_completed_at",
            field=models.DateTimeField(
                blank=True,
                null=True,
                verbose_name="Создание доставок завершено",
            ),
        ),
    ]
