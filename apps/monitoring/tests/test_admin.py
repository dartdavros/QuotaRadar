from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.monitoring.models import (
    MonitoringComponent,
    MonitoringEvent,
    MonitoringEventStatus,
)


class MonitoringEventAdminTests(TestCase):
    def setUp(self) -> None:
        self.user = get_user_model().objects.create_superuser(
            username="root",
            email="root@example.test",
            password="test-password",
        )
        self.client.force_login(self.user)
        self.event = MonitoringEvent.objects.create(
            component=MonitoringComponent.X,
            status=MonitoringEventStatus.SUCCESS,
            message="Проверка завершена.",
        )

    def test_changelist_displays_event(self) -> None:
        response = self.client.get(reverse("admin:monitoring_monitoringevent_changelist"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Проверка завершена.")

    def test_events_cannot_be_added_changed_or_deleted(self) -> None:
        add_response = self.client.get(
            reverse("admin:monitoring_monitoringevent_add")
        )
        change_url = reverse(
            "admin:monitoring_monitoringevent_change",
            args=(self.event.pk,),
        )
        change_response = self.client.post(change_url, {"message": "changed"})
        delete_response = self.client.get(
            reverse(
                "admin:monitoring_monitoringevent_delete",
                args=(self.event.pk,),
            )
        )

        self.assertEqual(add_response.status_code, 403)
        self.assertEqual(change_response.status_code, 403)
        self.assertEqual(delete_response.status_code, 403)
