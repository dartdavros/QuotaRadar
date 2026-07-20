from django.db import migrations

INITIAL_SOURCES = (
    {"provider": "openai", "username": "OpenAIDevs"},
    {"provider": "anthropic", "username": "ClaudeDevs"},
)


def create_initial_sources(apps, schema_editor):
    Source = apps.get_model("sources", "Source")
    for source in INITIAL_SOURCES:
        Source.objects.get_or_create(username=source["username"], defaults=source)


class Migration(migrations.Migration):
    dependencies = [("sources", "0001_initial")]

    operations = [
        migrations.RunPython(create_initial_sources, migrations.RunPython.noop)
    ]
