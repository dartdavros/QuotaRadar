from django.db import migrations


SYSTEM_PROMPT = """Ты классифицируешь публикации официальных аккаунтов разработчиков OpenAI и Anthropic. Определи, сообщает ли публикация о массовом сбросе квоты, повышении квоты или продлении периода повышенной квоты для Codex или Claude Code. Не считай релевантными общие релизы, документацию, исправления, локальные проблемы отдельного пользователя и сообщения без изменения квот. Возвращай только структурированный результат в формате, заданном приложением."""

USER_PROMPT = """Источник: {source}\nОжидаемый продукт: {expected_product}\nДата публикации: {published_at}\nСсылка: {source_url}\n\nТекст публикации:\n{normalized_text}\n\nДопустимые типы релевантного события: quota_reset, quota_increase, quota_extension. Для нерелевантной публикации укажи is_relevant=false."""


def create_initial_configuration(apps, schema_editor):
    PromptTemplate = apps.get_model("configuration", "PromptTemplate")
    SystemConfiguration = apps.get_model("configuration", "SystemConfiguration")
    prompt, _ = PromptTemplate.objects.get_or_create(
        code="quota_event_classifier",
        version=1,
        defaults={
            "system_prompt": SYSTEM_PROMPT,
            "user_prompt_template": USER_PROMPT,
            "is_active": True,
        },
    )
    SystemConfiguration.objects.get_or_create(id=1, defaults={"active_prompt": prompt})


def remove_initial_configuration(apps, schema_editor):
    SystemConfiguration = apps.get_model("configuration", "SystemConfiguration")
    PromptTemplate = apps.get_model("configuration", "PromptTemplate")
    SystemConfiguration.objects.filter(id=1).delete()
    PromptTemplate.objects.filter(code="quota_event_classifier", version=1).delete()


class Migration(migrations.Migration):
    dependencies = [("configuration", "0001_initial")]

    operations = [
        migrations.RunPython(create_initial_configuration, remove_initial_configuration)
    ]
