from django.db import migrations


TRUSTED_CODEX_SOURCES = (
    {
        "provider": "openai",
        "username": "thsottiaux",
        "enabled": False,
    },
    {
        "provider": "openai",
        "username": "sama",
        "enabled": False,
    },
)


def create_trusted_codex_sources(apps, schema_editor):
    Source = apps.get_model("sources", "Source")
    for source in TRUSTED_CODEX_SOURCES:
        Source.objects.get_or_create(
            username=source["username"],
            defaults=source,
        )


class Migration(migrations.Migration):
    dependencies = [("sources", "0003_sourcepost_processing_started_at")]

    operations = [
        migrations.RunPython(
            create_trusted_codex_sources,
            migrations.RunPython.noop,
        )
    ]
