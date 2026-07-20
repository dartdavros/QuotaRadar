from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("sources", "0002_initial_sources"),
    ]

    operations = [
        migrations.AddField(
            model_name="sourcepost",
            name="processing_started_at",
            field=models.DateTimeField(
                blank=True,
                null=True,
                verbose_name="Обработка начата",
            ),
        ),
    ]
