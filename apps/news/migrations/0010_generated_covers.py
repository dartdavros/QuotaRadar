"""Durable covers and a single paid generation claim; original-media identities remain unchanged."""
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("news", "0009_editorial_voice")]
    operations = [
        migrations.AddField(model_name="newspublication", name="cover_requested_at",
            field=models.DateTimeField(blank=True, editable=False, null=True)),
        migrations.AlterField(model_name="mediaasset", name="url",
            field=models.URLField(blank=True, max_length=2000)),
        migrations.AddField(model_name="mediaasset", name="origin",
            field=models.CharField(choices=[("source", "Источник"), ("generated", "Иллюстрация")],
                                   default="source", editable=False, max_length=16)),
        migrations.AddField(model_name="mediaasset", name="generated_content",
            field=models.BinaryField(blank=True, editable=False, null=True)),
        migrations.AddField(model_name="mediaasset", name="generation_metadata",
            field=models.JSONField(blank=True, default=dict, editable=False)),
        migrations.AddConstraint(model_name="mediaasset", constraint=models.CheckConstraint(
            condition=(models.Q(origin="source", generated_content__isnull=True)
                       | models.Q(origin="generated", kind="photo", generated_content__isnull=False)),
            name="news_media_origin_content")),
    ]
