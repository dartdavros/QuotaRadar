from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("advertising", "0002_campaign_body_alter_campaign_link_label_and_more")]

    operations = [
        migrations.AddField(
            model_name="campaign", name="emoji_fallbacks",
            field=models.JSONField(blank=True, default=dict, editable=False),
        ),
    ]
