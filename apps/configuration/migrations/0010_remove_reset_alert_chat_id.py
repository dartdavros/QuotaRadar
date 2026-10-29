"""Unconfirmed resets go to the group, so the owner alert chat is gone."""

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("configuration", "0009_reset_alert_chat_id")]
    operations = [
        migrations.RemoveField(model_name="systemconfiguration", name="reset_alert_chat_id"),
    ]
