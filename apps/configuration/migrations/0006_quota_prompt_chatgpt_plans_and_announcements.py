"""Quota classifier v3: ChatGPT paid plans cover Codex, scheduled resets count; keeps admin edits of v2."""
from django.db import migrations


ANCHOR = "Если связь публикации с изменением пользовательских лимитов отсутствует"

CLARIFICATIONS = """Уточнения для публикаций OpenAI:
- Лимиты Codex входят в платные планы ChatGPT. Если источник OpenAI сообщает о сбросе, повышении или продлении лимитов для всех платных аккаунтов ChatGPT, для платных планов ChatGPT (Plus, Pro, Business, Enterprise, Edu) или для всех платных пользователей, считай это изменением лимитов Codex, даже если Codex в публикации не назван.
- Не применяй это правило, если публикация явно ограничивает изменение отдельной функцией ChatGPT, не связанной с Codex, например генерацией изображений, видео или голосовым режимом.

Объявления о предстоящих изменениях:
- Объявление о запланированном массовом сбросе, повышении или продлении лимитов («tomorrow», «landing at 10am PST», «on Tuesday», «will reset») релевантно так же, как сообщение об уже выполненном изменении.
- В message_ru передай, что изменение ещё предстоит, и перенеси указанные дату, время и часовой пояс без пересчёта.

Сбои и сброс лимитов:
- Если публикация сообщает о сбое, замедлении или нагрузке и одновременно объявляет сброс, повышение или продление лимитов, она релевантна. Исключение о технических сбоях действует только тогда, когда квота не меняется.

"""


def with_clarifications(system_prompt):
    text = system_prompt.replace("\r\n", "\n")
    if ANCHOR in text:
        return text.replace(ANCHOR, CLARIFICATIONS + ANCHOR, 1)
    return text.rstrip() + "\n\n" + CLARIFICATIONS.rstrip()


def install(apps, schema_editor):
    Prompt = apps.get_model("configuration", "PromptTemplate")
    Config = apps.get_model("configuration", "SystemConfiguration")
    previous = Prompt.objects.filter(code="quota_event_classifier", version=2).first()
    if previous is None:
        return
    prompt, _ = Prompt.objects.get_or_create(code="quota_event_classifier", version=3, defaults={
        "system_prompt": with_clarifications(previous.system_prompt),
        "user_prompt_template": previous.user_prompt_template, "is_active": True})
    Config.objects.filter(active_prompt_id=previous.pk).update(active_prompt_id=prompt.pk)


def uninstall(apps, schema_editor):
    Prompt = apps.get_model("configuration", "PromptTemplate")
    Config = apps.get_model("configuration", "SystemConfiguration")
    previous = Prompt.objects.filter(code="quota_event_classifier", version=2).first()
    current = Prompt.objects.filter(code="quota_event_classifier", version=3).first()
    if previous is not None and current is not None:
        Config.objects.filter(active_prompt_id=current.pk).update(active_prompt_id=previous.pk)


class Migration(migrations.Migration):
    dependencies = [("configuration", "0005_trusted_source_prompt")]
    operations = [migrations.RunPython(install, uninstall)]
