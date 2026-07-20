from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True

    dependencies = [migrations.swappable_dependency(settings.AUTH_USER_MODEL)]

    operations = [
        migrations.CreateModel(
            name="EncryptedSecret",
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
                    "code",
                    models.CharField(
                        choices=[
                            ("telegram_bot_token", "Telegram Bot Token"),
                            ("llm_api_key", "Ключ API ИИ-провайдера"),
                            ("x_bearer_token", "X Bearer Token"),
                            ("proxy_url", "URL прокси"),
                        ],
                        max_length=64,
                        unique=True,
                        verbose_name="Код",
                    ),
                ),
                (
                    "encrypted_value",
                    models.BinaryField(
                        blank=True,
                        editable=False,
                        null=True,
                        verbose_name="Зашифрованное значение",
                    ),
                ),
                (
                    "key_version",
                    models.CharField(
                        blank=True, max_length=64, verbose_name="Версия ключа"
                    ),
                ),
                (
                    "updated_at",
                    models.DateTimeField(auto_now=True, verbose_name="Изменён"),
                ),
                (
                    "updated_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="updated_quota_radar_secrets",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Изменил",
                    ),
                ),
            ],
            options={
                "verbose_name": "Секрет",
                "verbose_name_plural": "Секреты",
                "ordering": ("code",),
                "permissions": (
                    ("view_secret_value", "Может просматривать расшифрованные секреты"),
                    ("change_secret_value", "Может изменять значения секретов"),
                ),
            },
        )
    ]
