import django.core.validators
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("configuration", "0002_initial_configuration")]

    operations = [
        migrations.AddField(
            model_name="systemconfiguration",
            name="bootstrap_post_limit",
            field=models.PositiveIntegerField(
                default=10,
                help_text=(
                    "Количество последних постов в единственной странице первого "
                    "опроса источника. Допустимо от 5 до 100."
                ),
                validators=[
                    django.core.validators.MinValueValidator(5),
                    django.core.validators.MaxValueValidator(100),
                ],
                verbose_name="Постов при первом опросе",
            ),
        ),
        migrations.AddField(
            model_name="systemconfiguration",
            name="regular_poll_post_limit",
            field=models.PositiveIntegerField(
                default=5,
                help_text=(
                    "Размер страницы X API при последующих опросах. Если новых "
                    "постов больше, система продолжает пагинацию. Допустимо от 5 "
                    "до 100."
                ),
                validators=[
                    django.core.validators.MinValueValidator(5),
                    django.core.validators.MaxValueValidator(100),
                ],
                verbose_name="Постов на страницу регулярного опроса",
            ),
        ),
    ]
