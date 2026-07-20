from django.db import migrations


SECRET_CODES = (
    "telegram_bot_token",
    "llm_api_key",
    "x_bearer_token",
    "proxy_url",
)


def create_secret_rows(apps, schema_editor):
    EncryptedSecret = apps.get_model("secrets", "EncryptedSecret")
    for code in SECRET_CODES:
        EncryptedSecret.objects.get_or_create(code=code)


def remove_secret_rows(apps, schema_editor):
    EncryptedSecret = apps.get_model("secrets", "EncryptedSecret")
    EncryptedSecret.objects.filter(
        code__in=SECRET_CODES, encrypted_value__isnull=True
    ).delete()


class Migration(migrations.Migration):
    dependencies = [("secrets", "0001_initial")]

    operations = [migrations.RunPython(create_secret_rows, remove_secret_rows)]
