from unittest.mock import patch

from django.contrib.admin.helpers import ACTION_CHECKBOX_NAME
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.configuration.models import SystemConfiguration
from apps.sources.models import Source, SourcePost, SourcePostProcessingStatus


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

    def test_only_enabled_flag_is_editable_for_trusted_sources(self) -> None:
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

    def test_source_list_exposes_historical_import_action(self) -> None:
        response = self.client.get(reverse("admin:sources_source_changelist"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Подтянуть старые посты выбранных источников")
        self.assertContains(response, ACTION_CHECKBOX_NAME)

    @patch("apps.sources.admin.backfill_source.delay")
    def test_historical_import_action_queues_selected_sources(self, delay) -> None:
        source = Source.objects.get(username="OpenAIDevs")

        response = self.client.post(
            reverse("admin:sources_source_changelist"),
            {
                "action": "queue_historical_backfill",
                ACTION_CHECKBOX_NAME: [str(source.pk)],
                "index": "0",
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "Задач исторического импорта поставлено в очередь: 1.",
        )
        delay.assert_called_once_with(source.pk)

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


class SourcePostAdminTests(TestCase):
    def setUp(self) -> None:
        self.user = get_user_model().objects.create_superuser(
            username="root-posts",
            email="root-posts@example.test",
            password="test-password",
        )
        self.client.force_login(self.user)
        source = Source.objects.get(username="OpenAIDevs")
        self.post = SourcePost.objects.create(
            source=source,
            external_id="admin-9001",
            text="Post",
            normalized_text="Post",
            source_url="https://x.com/OpenAIDevs/status/9001",
            published_at=timezone.now(),
            raw_data={},
            processing_status=SourcePostProcessingStatus.FAILED,
            last_error="Configuration error.",
        )

    def test_changelist_exposes_bulk_requeue_action(self) -> None:
        response = self.client.get(reverse("admin:sources_sourcepost_changelist"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "Вернуть выбранные ошибочные посты в очередь анализа",
        )
        self.assertContains(response, ACTION_CHECKBOX_NAME)

    @patch("apps.monitoring.dispatch.analyze_post.delay")
    def test_bulk_action_requeues_failed_post(self, delay) -> None:
        response = self.client.post(
            reverse("admin:sources_sourcepost_changelist"),
            {
                "action": "requeue_failed_posts",
                ACTION_CHECKBOX_NAME: [str(self.post.pk)],
                "index": "0",
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Поставлено в очередь анализа: 1.")
        delay.assert_called_once_with(self.post.pk)
        self.post.refresh_from_db()
        self.assertEqual(
            self.post.processing_status,
            SourcePostProcessingStatus.QUEUED,
        )
        self.assertIsNotNone(self.post.processing_started_at)
        self.assertEqual(self.post.last_error, "")
