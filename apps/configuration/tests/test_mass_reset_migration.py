from importlib import import_module

from django.apps import apps
from django.test import TestCase

from apps.configuration.models import PromptTemplate, SystemConfiguration

install = import_module(
    "apps.configuration.migrations.0007_implicit_mass_reset_prompt"
).install


class MassResetMigrationTests(TestCase):
    def test_customized_v3_is_preserved_when_v4_is_created_and_selected(self):
        cfg = SystemConfiguration.load()
        previous = PromptTemplate.objects.get(code="quota_event_classifier", version=3)
        PromptTemplate.objects.filter(pk=cfg.active_prompt_id).update(version=40)
        PromptTemplate.objects.filter(pk=previous.pk).update(
            system_prompt="Правило владельца.\nЕсли связь публикации с изменением пользовательских лимитов отсутствует, отклони.",
            user_prompt_template="Собственный шаблон: {normalized_text}",
        )
        SystemConfiguration.objects.filter(pk=cfg.pk).update(active_prompt_id=previous.pk)

        install(apps, None)

        cfg.refresh_from_db()
        self.assertEqual(cfg.active_prompt.version, 4)
        self.assertIn("Правило владельца.", cfg.active_prompt.system_prompt)
        self.assertIn("Global reset by EOD", cfg.active_prompt.system_prompt)
        self.assertEqual(cfg.active_prompt.user_prompt_template, "Собственный шаблон: {normalized_text}")
        previous.refresh_from_db()
        self.assertNotIn("Global reset by EOD", previous.system_prompt)

    def test_existing_v4_edits_and_custom_prompt_selection_are_not_overwritten(self):
        cfg = SystemConfiguration.load()
        current = cfg.active_prompt
        current.system_prompt = "Отредактированный v4 владельца"
        current.save(update_fields=("system_prompt",))
        custom = PromptTemplate.objects.create(
            code="owner_classifier", version=1, system_prompt="Другой промпт",
            user_prompt_template="{normalized_text}", is_active=True,
        )
        cfg.active_prompt = custom
        cfg.save(update_fields=("active_prompt",))

        install(apps, None)

        cfg.refresh_from_db()
        current.refresh_from_db()
        self.assertEqual(cfg.active_prompt_id, custom.pk)
        self.assertEqual(current.system_prompt, "Отредактированный v4 владельца")
