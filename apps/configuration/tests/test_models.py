from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.configuration.models import PromptTemplate, SystemConfiguration


class SystemConfigurationTests(TestCase):
    def test_initial_prompt_and_singleton_are_created(self) -> None:
        configuration = SystemConfiguration.load()

        self.assertEqual(configuration.pk, SystemConfiguration.SINGLETON_PK)
        self.assertEqual(configuration.poll_interval_seconds, 300)
        self.assertEqual(configuration.bootstrap_post_limit, 10)
        self.assertEqual(configuration.regular_poll_post_limit, 5)
        self.assertEqual(configuration.active_prompt.code, "quota_event_classifier")
        self.assertEqual(configuration.active_prompt.version, 1)

    def test_post_limits_must_match_x_api_bounds(self) -> None:
        configuration = SystemConfiguration.load()

        for field_name, invalid_value in (
            ("bootstrap_post_limit", 4),
            ("bootstrap_post_limit", 101),
            ("regular_poll_post_limit", 4),
            ("regular_poll_post_limit", 101),
        ):
            with self.subTest(field_name=field_name, invalid_value=invalid_value):
                setattr(configuration, field_name, invalid_value)
                with self.assertRaises(ValidationError):
                    configuration.full_clean()
                configuration.refresh_from_db()

    def test_model_rejects_non_singleton_primary_key(self) -> None:
        prompt = PromptTemplate.objects.create(
            code="secondary",
            version=1,
            system_prompt="system",
            user_prompt_template="user",
        )
        configuration = SystemConfiguration(pk=2, active_prompt=prompt)

        with self.assertRaises(ValidationError):
            configuration.clean()

    def test_model_rejects_duplicate_code_and_version(self) -> None:
        with self.assertRaises(ValidationError):
            PromptTemplate.objects.create(
                code="quota_event_classifier",
                version=1,
                system_prompt="system",
                user_prompt_template="user",
                is_active=True,
            )

    def test_prompt_version_can_be_switched_without_activation_deadlock(self) -> None:
        configuration = SystemConfiguration.load()
        previous_prompt = configuration.active_prompt
        next_prompt = PromptTemplate.objects.create(
            code=previous_prompt.code,
            version=2,
            system_prompt="new system",
            user_prompt_template="new user",
            is_active=True,
        )

        configuration.active_prompt = next_prompt
        configuration.save()
        previous_prompt.is_active = False
        previous_prompt.save()

        self.assertFalse(previous_prompt.is_active)
        self.assertEqual(SystemConfiguration.load().active_prompt, next_prompt)

    def test_active_prompt_cannot_be_disabled(self) -> None:
        prompt = SystemConfiguration.load().active_prompt
        prompt.is_active = False

        with self.assertRaises(ValidationError):
            prompt.save()

    def test_new_instance_cannot_overwrite_existing_singleton(self) -> None:
        prompt = PromptTemplate.objects.create(
            code="replacement-attempt",
            version=1,
            system_prompt="system",
            user_prompt_template="user",
        )
        duplicate = SystemConfiguration(active_prompt=prompt)

        with self.assertRaises(ValidationError):
            duplicate.save()

        self.assertNotEqual(SystemConfiguration.load().active_prompt, prompt)

    def test_save_rejects_non_singleton_primary_key(self) -> None:
        prompt = PromptTemplate.objects.create(
            code="secondary-save",
            version=1,
            system_prompt="system",
            user_prompt_template="user",
        )
        configuration = SystemConfiguration(pk=2, active_prompt=prompt)

        with self.assertRaises(ValidationError):
            configuration.save()
