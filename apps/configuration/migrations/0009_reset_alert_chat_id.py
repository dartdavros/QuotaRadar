"""Optional owner chat for unconfirmed mass reset alerts."""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("configuration", "0008_day_series_reset_prompt")]
    operations = [
        migrations.AddField(
            model_name="systemconfiguration",
            name="reset_alert_chat_id",
            field=models.CharField(
                blank=True,
                help_text=(
                    "Числовой chat ID или @username. Пока поле пустое, сигналы не отправляются. "
                    "Это служебное оповещение владельцу, а не публикация для подписчиков."
                ),
                max_length=128,
                verbose_name="Чат для сигналов о неподтверждённом сбросе",
            ),
        ),
    ]
