"""Date-aware editorial prompts and cache-independent hashes for unsent publications."""
from hashlib import sha256
import json
from django.db import migrations

RULES = {
    "writing": """
publication_time — время будущей публикации, sources.date — дата события.
Для historical=true описывай событие с его настоящей датой; не выдавай его за сегодняшний запуск.
Не используй «сегодня», «вчера», «только что», «прямо сейчас» в исторической новости.
Не превращай прошлое обещание, акцию или временную доступность в утверждение о настоящем.""",
    "verification": """
Сопоставь формулировки времени с publication_time и sources.date.
Для historical=true дополнительно верни still_relevant: сохраняется ли польза новости сейчас.
Откажи для истёкших акций, старых сбоев, устаревших обещаний и ложной сегодняшней срочности.
Относительные даты «сегодня», «вчера», «только что», «прямо сейчас» в историческом тексте запрещены.
Если текущая доступность не следует из источников, её нельзя утверждать.""",
}


def install(apps, schema_editor):
    Prompt = apps.get_model("configuration", "PromptTemplate")
    Config = apps.get_model("news", "NewsConfiguration")
    for stage, rules in RULES.items():
        previous = Prompt.objects.filter(code=f"news_{stage}", version=1).first()
        if not previous:
            continue
        prompt, _ = Prompt.objects.get_or_create(code=previous.code, version=2, defaults={
            "system_prompt": previous.system_prompt + rules,
            "user_prompt_template": previous.user_prompt_template, "is_active": True})
        Config.objects.filter(**{f"{stage}_prompt_id": previous.pk}).update(**{f"{stage}_prompt_id": prompt.pk})
    Publication = apps.get_model("news", "NewsPublication")
    Media = apps.get_model("news", "MediaAsset")
    for publication in Publication.objects.filter(status="ready").exclude(payload_hash="").iterator():
        media = list(Media.objects.filter(publication_id=publication.pk).order_by("position", "pk").values(
            "kind", "position", "url", "media_key"))
        publication.payload_hash = sha256(json.dumps({
            "html": publication.rendered, "media": media}, sort_keys=True).encode()).hexdigest()
        publication.save(update_fields=("payload_hash",))


class Migration(migrations.Migration):
    dependencies = [("news", "0003_mediaasset_telegram_bot_identity_and_more")]
    operations = [migrations.RunPython(install, migrations.RunPython.noop)]
