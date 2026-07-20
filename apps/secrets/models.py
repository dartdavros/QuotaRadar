"""Encrypted application-secret metadata models."""

from __future__ import annotations

from django.conf import settings
from django.db import models


class SecretCode(models.TextChoices):
    TELEGRAM_BOT_TOKEN = "telegram_bot_token", "Telegram Bot Token"
    LLM_API_KEY = "llm_api_key", "Ключ API ИИ-провайдера"
    X_BEARER_TOKEN = "x_bearer_token", "X Bearer Token"
    PROXY_URL = "proxy_url", "URL прокси"


class EncryptedSecret(models.Model):
    """Ciphertext and audit metadata for one known application secret."""

    code = models.CharField(
        "Код",
        max_length=64,
        unique=True,
        choices=SecretCode.choices,
    )
    encrypted_value = models.BinaryField(
        "Зашифрованное значение",
        null=True,
        blank=True,
        editable=False,
    )
    key_version = models.CharField("Версия ключа", max_length=64, blank=True)
    updated_at = models.DateTimeField("Изменён", auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="Изменил",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="updated_quota_radar_secrets",
    )

    class Meta:
        verbose_name = "Секрет"
        verbose_name_plural = "Секреты"
        ordering = ("code",)
        permissions = (
            ("view_secret_value", "Может просматривать расшифрованные секреты"),
            ("change_secret_value", "Может изменять значения секретов"),
        )

    @property
    def is_configured(self) -> bool:
        return bool(self.encrypted_value and self.key_version)

    def __str__(self) -> str:
        return self.get_code_display()
