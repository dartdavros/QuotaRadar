from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("analysis", "0002_analysis_delivery_fanout_completed_at"),
    ]

    operations = [
        migrations.AddField(
            model_name="analysis",
            name="is_fallback",
            field=models.BooleanField(
                default=False,
                help_text="Отправлено без LLM, потому что она была недоступна.",
                verbose_name="Предупреждение по ключевому слову",
            ),
        ),
    ]
