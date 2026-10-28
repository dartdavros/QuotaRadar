"""Classifier v5 preserves v4 edits and recognizes the Day N / reset series."""

from django.db import migrations

CLARIFICATIONS = """Короткие объявления доверенных источников о массовом сбросе:
- @thsottiaux — утверждённый источник событий пользовательских квот Codex.
- Его прямое объявление о сбросе пользовательской квоты относится к Codex, даже если
  название продукта и слова limits, usage, quota, tokens в тексте опущены.
- Примеры релевантных объявлений: «Global reset by EOD. May the tokens do good things
  for you.»; «Reset will land around 14pm PST tomorrow.». Не выдумывай часовой пояс.
- Само по себе слово reset недостаточно. Не подпадают под это правило вопросы,
  предположения, пожелания и просьбы других людей, рассуждения о прошлых или будущих
  сбросах без объявления нового, шутки про кнопку сброса, а также сброс Git, настроек,
  паролей, инфраструктуры, программного API или одного аккаунта.
- Родительский пост с указанным автором является контекстом ответа. Не приписывай
  его утверждения автору текущего поста и не считай простой ответ новым объявлением.

Ежедневная рубрика @thsottiaux «Day N/»:
- @thsottiaux ведёт ежедневную рубрику: пост начинается с «Day N/», дальше идёт
  сегодняшний пункт — либо возможность продукта, либо сброс квоты.
- Если в собственном тексте поста сказано, что сегодняшний пункт — это сброс
  («Day 6/ Reset», «Day 20/ Rest and reset», «today is a reset», «it's reset day today»,
  «that's a reset», «Le limit reset»), это quota_reset для Codex, даже без слов limits,
  usage, quota и tokens.
- Подводка, шутка или ложное начало перед таким сообщением его не отменяют: «Bet you
  thought we forgot, but no, it's reset day today»; «Much requested <функция>. Just
  kidding, today is a reset». Упомянутая или процитированная в том же посте возможность
  продукта тоже его не отменяет: событием считается сброс.
- Если автор пишет, что сегодня сброса нет, применяй обычные правила: явное отрицание —
  нерелевантно, объявление о предстоящем сбросе — релевантно с указанием, что изменение
  ещё предстоит.

"""
REPLACED = "Короткие объявления доверенных источников о массовом сбросе:"
ANCHOR = "Если связь публикации с изменением пользовательских лимитов отсутствует"


def _upgrade(text: str) -> str:
    """Replace the trusted-source block in place, keeping every owner edit around it."""

    start = text.find(REPLACED)
    end = text.find(ANCHOR)
    if 0 <= start < end:
        return text[:start] + CLARIFICATIONS + text[end:]
    if end >= 0:
        return text[:end] + CLARIFICATIONS + text[end:]
    return text.rstrip() + "\n\n" + CLARIFICATIONS.rstrip()


def install(apps, schema_editor):
    Prompt = apps.get_model("configuration", "PromptTemplate")
    Config = apps.get_model("configuration", "SystemConfiguration")
    previous = Prompt.objects.filter(code="quota_event_classifier", version=4).first()
    if previous is None:
        return
    prompt, _ = Prompt.objects.get_or_create(
        code="quota_event_classifier", version=5,
        defaults={"system_prompt": _upgrade(previous.system_prompt.replace("\r\n", "\n")),
                  "user_prompt_template": previous.user_prompt_template, "is_active": True},
    )
    Config.objects.filter(active_prompt_id=previous.pk).update(active_prompt_id=prompt.pk)


def uninstall(apps, schema_editor):
    Prompt = apps.get_model("configuration", "PromptTemplate")
    Config = apps.get_model("configuration", "SystemConfiguration")
    previous = Prompt.objects.filter(code="quota_event_classifier", version=4).first()
    current = Prompt.objects.filter(code="quota_event_classifier", version=5).first()
    if previous is not None and current is not None:
        Config.objects.filter(active_prompt_id=current.pk).update(active_prompt_id=previous.pk)


class Migration(migrations.Migration):
    dependencies = [("configuration", "0007_implicit_mass_reset_prompt")]
    operations = [migrations.RunPython(install, uninstall)]
