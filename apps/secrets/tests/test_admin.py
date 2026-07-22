from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase
from django.urls import reverse

from apps.secrets.models import EncryptedSecret, SecretCode
from apps.secrets.services import get_secret, set_secret
from tests._otp import force_login_verified


class EncryptedSecretAdminPermissionTests(TestCase):
    def setUp(self) -> None:
        user_model = get_user_model()
        self.secret = EncryptedSecret.objects.get(code=SecretCode.PROXY_URL)
        self.plaintext = "http://proxy-user:proxy-password@proxy.example:8080"
        self.superuser = user_model.objects.create_superuser(
            username="root",
            email="root@example.test",
            password="test-password",
        )
        set_secret(self.secret.code, self.plaintext, updated_by=self.superuser)
        self.url = reverse(
            "admin:secrets_encryptedsecret_change", args=(self.secret.pk,)
        )

    def _create_user_with_permissions(self, username: str, *codenames: str):
        user = get_user_model().objects.create_user(
            username=username,
            password="test-password",
            is_staff=True,
        )
        user.user_permissions.add(*Permission.objects.filter(codename__in=codenames))
        return user

    def test_user_without_value_permission_does_not_receive_plaintext(self) -> None:
        user = self._create_user_with_permissions("metadata", "view_encryptedsecret")
        force_login_verified(self.client, user)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, self.plaintext)
        self.assertNotContains(response, "proxy-password")

    def test_user_with_view_value_permission_receives_decrypted_value(self) -> None:
        user = self._create_user_with_permissions(
            "viewer",
            "view_encryptedsecret",
            "view_secret_value",
        )
        force_login_verified(self.client, user)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.plaintext)

    def test_authorized_change_reencrypts_and_audits_secret(self) -> None:
        user = self._create_user_with_permissions(
            "editor",
            "view_encryptedsecret",
            "change_encryptedsecret",
            "change_secret_value",
        )
        force_login_verified(self.client, user)
        replacement = "http://new-user:new-password@proxy.example:8081"

        response = self.client.post(
            self.url,
            {
                "secret_value": replacement,
                "clear_value": "",
                "_save": "Сохранить",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.secret.refresh_from_db()
        self.assertEqual(self.secret.updated_by, user)
        self.assertEqual(get_secret(self.secret.code), replacement)
        self.assertNotIn(replacement.encode(), bytes(self.secret.encrypted_value))
