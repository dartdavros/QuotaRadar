from django.db import migrations


SYSTEM_PROMPT = """Ты классифицируешь публикации доверенных X-источников OpenAI и Anthropic. Источник может быть официальным корпоративным аккаунтом или заранее утверждённым аккаунтом руководителя продукта. Определи, содержит ли публикация прямое фактическое объявление о массовом сбросе квоты, повышении квоты или продлении периода повышенной квоты для Codex или Claude Code. Считай событие релевантным только тогда, когда изменение относится к группе пользователей, тарифу или всем пользователям, а не к одному аккаунту. Не считай релевантными предположения, обсуждения, ответы без нового объявления, статистику использования, общие релизы, документацию, исправления, локальные проблемы отдельного пользователя и сообщения без изменения квот. Возвращай только структурированный результат в формате, заданном приложением."""

USER_PROMPT = """Источник: {source}\nОжидаемый продукт: {expected_product}\nДата публикации: {published_at}\nСсылка: {source_url}\n\nТекст публикации:\n{normalized_text}\n\nДопустимые типы релевантного события: quota_reset, quota_increase, quota_extension. Для нерелевантной публикации укажи is_relevant=false."""


def create_trusted_source_prompt(apps, schema_editor):
    PromptTemplate = apps.get_model("configuration", "PromptTemplate")
    SystemConfiguration = apps.get_model("configuration", "SystemConfiguration")

    prompt, _ = PromptTemplate.objects.update_or_create(
        code="quota_event_classifier",
        version=2,
        defaults={
            "system_prompt": SYSTEM_PROMPT,
            "user_prompt_template": USER_PROMPT,
            "is_active": True,
        },
    )

    configuration = SystemConfiguration.objects.filter(id=1).select_related(
        "active_prompt"
    ).first()
    if configuration is None:
        return
    if (
        configuration.active_prompt.code == "quota_event_classifier"
        and configuration.active_prompt.version == 1
    ):
        configuration.active_prompt = prompt
        configuration.save(update_fields=("active_prompt",))


def remove_trusted_source_prompt(apps, schema_editor):
    PromptTemplate = apps.get_model("configuration", "PromptTemplate")
    SystemConfiguration = apps.get_model("configuration", "SystemConfiguration")

    previous_prompt = PromptTemplate.objects.filter(
        code="quota_event_classifier",
        version=1,
    ).first()
    configuration = SystemConfiguration.objects.filter(id=1).select_related(
        "active_prompt"
    ).first()
    if (
        configuration is not None
        and previous_prompt is not None
        and configuration.active_prompt.code == "quota_event_classifier"
        and configuration.active_prompt.version == 2
    ):
        configuration.active_prompt = previous_prompt
        configuration.save(update_fields=("active_prompt",))

    PromptTemplate.objects.filter(
        code="quota_event_classifier",
        version=2,
    ).delete()


class Migration(migrations.Migration):
    dependencies = [("configuration", "0004_backfill_and_telegram_timezone")]

    operations = [
        migrations.RunPython(
            create_trusted_source_prompt,
            remove_trusted_source_prompt,
        )
    ]
