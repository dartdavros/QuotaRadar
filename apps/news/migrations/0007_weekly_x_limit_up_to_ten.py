from decimal import Decimal

import django.core.validators
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("news", "0006_writing_prompt_length_follows_facts")]

    operations = [
        migrations.AlterField(
            model_name="newsconfiguration",
            name="weekly_x_limit",
            field=models.DecimalField(
                decimal_places=3, default=Decimal("3.000"), max_digits=6,
                validators=[django.core.validators.MinValueValidator(Decimal("0.100")),
                            django.core.validators.MaxValueValidator(Decimal("10.000"))],
                verbose_name="Недельный бюджет новых X-запросов, USD"),
        ),
    ]
