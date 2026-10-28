from importlib import import_module

from django.apps import apps
from django.test import TestCase

from apps.configuration.models import PromptTemplate, SystemConfiguration

install = import_module(
    "apps.configuration.migrations.0008_day_series_reset_prompt"
).install

OWNER_V4 = (
    "Правило владельца.\n\n"
    "Короткие объявления доверенных источников о массовом сбросе:\n"
    "- старый блок про tokens.\n\n"
    "Если связь публикации с изменением пользовательских лимитов отсутствует, отклони."
)


class DaySeriesMigrationTests(TestCase):
    def setUp(self):
        self.cfg = SystemConfiguration.load()
        self.previous = PromptTemplate.objects.get(code="quota_event_classifier", version=4)
        # The suite runs on a migrated database: move the shipped v5 aside and start from v4.
        PromptTemplate.objects.filter(pk=self.cfg.active_prompt_id).update(version=50)
        SystemConfiguration.objects.filter(pk=self.cfg.pk).update(active_prompt_id=self.previous.pk)

    def select_v4_with(self, system_prompt):
        PromptTemplate.objects.filter(pk=self.previous.pk).update(
            system_prompt=system_prompt,
            user_prompt_template="Собственный шаблон: {normalized_text}",
        )

    def test_customized_v4_is_preserved_when_v5_is_created_and_selected(self):
        self.select_v4_with(OWNER_V4)

        install(apps, None)

        self.cfg.refresh_from_db()
        self.assertEqual(self.cfg.active_prompt.version, 5)
        text = self.cfg.active_prompt.system_prompt
        self.assertIn("Правило владельца.", text)
        self.assertIn("Ежедневная рубрика @thsottiaux", text)
        self.assertIn("Если связь публикации", text)
        self.assertNotIn("старый блок про tokens", text)
        self.assertEqual(
            self.cfg.active_prompt.user_prompt_template, "Собственный шаблон: {normalized_text}"
        )
        self.previous.refresh_from_db()
        self.assertIn("старый блок про tokens", self.previous.system_prompt)
        self.assertNotIn("Ежедневная рубрика", self.previous.system_prompt)

    def test_prompt_without_the_known_block_keeps_every_owner_rule(self):
        self.select_v4_with("Только правило владельца.")

        install(apps, None)

        self.cfg.refresh_from_db()
        self.assertEqual(self.cfg.active_prompt.version, 5)
        self.assertIn("Только правило владельца.", self.cfg.active_prompt.system_prompt)
        self.assertIn("Ежедневная рубрика @thsottiaux", self.cfg.active_prompt.system_prompt)

    def test_custom_prompt_selection_is_not_overwritten(self):
        custom = PromptTemplate.objects.create(
            code="owner_classifier", version=1, system_prompt="Другой промпт",
            user_prompt_template="{normalized_text}", is_active=True,
        )
        SystemConfiguration.objects.filter(pk=self.cfg.pk).update(active_prompt_id=custom.pk)

        install(apps, None)

        self.cfg.refresh_from_db()
        self.assertEqual(self.cfg.active_prompt_id, custom.pk)
