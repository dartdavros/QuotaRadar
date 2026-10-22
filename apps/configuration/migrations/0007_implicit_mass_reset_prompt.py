"""Classifier v4 preserves v3 edits and identifies implicit trusted-source resets."""

from django.db import migrations

CLARIFICATIONS = """Короткие объявления доверенных источников о массовом сбросе:
- @thsottiaux — утверждённый источник событий пользовательских квот Codex.
- Его прямое объявление о глобальном сбросе пользовательской квоты с упоминанием
  tokens относится к Codex, даже если название продукта в тексте опущено.
- Пример: «Global reset by EOD. May the tokens do good things for you.» —
  релевантный quota_reset, запланированный до конца дня (EOD). Не выдумывай часовой пояс.
- Само по себе слово reset недостаточно. Вопросы, предположения, сброс Git,
  настроек, инфраструктуры, программного API или одного аккаунта не подпадают
  под это правило.
- Родительский пост с указанным автором является контекстом ответа. Не приписывай
  его утверждения автору текущего поста и не считай простой ответ новым объявлением.

"""
ANCHOR = "Если связь публикации с изменением пользовательских лимитов отсутствует"


def install(apps, schema_editor):
    Prompt = apps.get_model("configuration", "PromptTemplate")
    Config = apps.get_model("configuration", "SystemConfiguration")
    previous = Prompt.objects.filter(code="quota_event_classifier", version=3).first()
    if previous is None:
        return
    text = previous.system_prompt.replace("\r\n", "\n")
    if ANCHOR in text:
        text = text.replace(ANCHOR, CLARIFICATIONS + ANCHOR, 1)
    else:
        text = text.rstrip() + "\n\n" + CLARIFICATIONS.rstrip()
    prompt, _ = Prompt.objects.get_or_create(
        code="quota_event_classifier", version=4,
        defaults={"system_prompt": text,
                  "user_prompt_template": previous.user_prompt_template, "is_active": True},
    )
    Config.objects.filter(active_prompt_id=previous.pk).update(active_prompt_id=prompt.pk)


def uninstall(apps, schema_editor):
    Prompt = apps.get_model("configuration", "PromptTemplate")
    Config = apps.get_model("configuration", "SystemConfiguration")
    previous = Prompt.objects.filter(code="quota_event_classifier", version=3).first()
    current = Prompt.objects.filter(code="quota_event_classifier", version=4).first()
    if previous is not None and current is not None:
        Config.objects.filter(active_prompt_id=current.pk).update(active_prompt_id=previous.pk)


class Migration(migrations.Migration):
    dependencies = [("configuration", "0006_quota_prompt_chatgpt_plans_and_announcements")]
    operations = [migrations.RunPython(install, uninstall)]
