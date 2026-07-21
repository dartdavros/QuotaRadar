from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.configuration.models import SystemConfiguration
from apps.sources.models import Source


class SourceAdminTests(TestCase):
    def setUp(self) -> None:
        self.user = get_user_model().objects.create_superuser(
            username="root",
            email="root@example.test",
            password="test-password",
        )
        self.client.force_login(self.user)

    def test_source_change_page_displays_polling_state(self) -> None:
        source = Source.objects.get(username="OpenAIDevs")
        source.x_user_id = "1001"
        source.last_post_id = "105"
        source.last_error = "safe error"
        source.save()

        response = self.client.get(
            reverse("admin:sources_source_change", args=(source.pk,))
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "1001")
        self.assertContains(response, "105")
        self.assertContains(response, "safe error")

    def test_only_enabled_flag_is_editable_for_official_sources(self) -> None:
        source = Source.objects.get(username="OpenAIDevs")
        response = self.client.get(
            reverse("admin:sources_source_change", args=(source.pk,))
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'name="provider"')
        self.assertNotContains(response, 'name="username"')
        self.assertContains(response, 'name="enabled"')

    def test_new_sources_cannot_be_added_in_admin(self) -> None:
        response = self.client.get(reverse("admin:sources_source_add"))

        self.assertEqual(response.status_code, 403)

    def test_source_list_displays_runtime_status(self) -> None:
        configuration = SystemConfiguration.load()
        configuration.monitoring_enabled = True
        configuration.save()
        source = Source.objects.get(username="OpenAIDevs")
        source.last_checked_at = timezone.now()
        source.last_success_at = source.last_checked_at
        source.last_error = ""
        source.save()

        response = self.client.get(reverse("admin:sources_source_changelist"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Работает")
