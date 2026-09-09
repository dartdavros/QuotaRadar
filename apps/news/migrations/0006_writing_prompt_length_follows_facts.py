"""Writing prompt v4: length follows the facts; a short source makes a short post."""
from django.db import migrations

OLD = """"text" — сама новость. Два-три коротких абзаца, разделённых пустой строкой, всего 400–750 символов. Первый абзац не повторяет заголовок ни дословно, ни по смыслу, а сразу даёт следующий факт."""
NEW = """"text" — сама новость. Обычно два-три коротких абзаца, разделённых пустой строкой, но объём задают факты: если источник короткий, пиши коротко и ничего не додумывай ради длины. Первый абзац не повторяет заголовок ни дословно, ни по смыслу, а сразу даёт следующий факт."""


def install(apps, schema_editor):
    Prompt = apps.get_model("configuration", "PromptTemplate")
    Config = apps.get_model("news", "NewsConfiguration")
    previous = Prompt.objects.filter(code="news_writing", version=3).first()
    if not previous or OLD not in previous.system_prompt:
        return
    prompt, _ = Prompt.objects.get_or_create(code="news_writing", version=4, defaults={
        "system_prompt": previous.system_prompt.replace(OLD, NEW),
        "user_prompt_template": previous.user_prompt_template, "is_active": True})
    Config.objects.filter(writing_prompt_id=previous.pk).update(writing_prompt_id=prompt.pk)


class Migration(migrations.Migration):
    dependencies = [("news", "0005_writing_prompt_names_its_fields")]
    operations = [migrations.RunPython(install, migrations.RunPython.noop)]
