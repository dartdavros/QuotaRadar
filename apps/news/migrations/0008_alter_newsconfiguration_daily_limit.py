import django.core.validators
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("news", "0007_weekly_x_limit_up_to_ten")]

    operations = [
        migrations.AlterField(
            model_name="newsconfiguration",
            name="daily_limit",
            field=models.PositiveSmallIntegerField(
                default=3,
                validators=[django.core.validators.MinValueValidator(1),
                            django.core.validators.MaxValueValidator(20)],
                verbose_name="Максимум публикаций в сутки"),
        ),
    ]
