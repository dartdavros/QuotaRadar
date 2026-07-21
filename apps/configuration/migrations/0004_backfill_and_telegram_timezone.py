import django.core.validators
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("configuration", "0003_systemconfiguration_post_limits")]

    operations = [
        migrations.AddField(
            model_name="systemconfiguration",
            name="historical_backfill_post_limit",
            field=models.PositiveIntegerField(
                default=100,
                help_text=(
                    "Максимальное количество старых постов, загружаемых одним "
                    "ручным импортом для выбранного источника. Допустимо от 5 "
                    "до 3200."
                ),
                validators=[
                    django.core.validators.MinValueValidator(5),
                    django.core.validators.MaxValueValidator(3200),
                ],
                verbose_name="Постов за исторический импорт",
            ),
        ),
        migrations.AddField(
            model_name="systemconfiguration",
            name="telegram_message_timezone",
            field=models.CharField(
                default="Europe/Moscow",
                help_text=(
                    "IANA-имя часового пояса для даты исходной публикации, "
                    "например Europe/Moscow или UTC."
                ),
                max_length=64,
                verbose_name="Часовой пояс даты в Telegram",
            ),
        ),
    ]
