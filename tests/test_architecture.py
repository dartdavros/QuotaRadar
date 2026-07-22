from __future__ import annotations

import ast
from pathlib import Path

from django.test import SimpleTestCase

ROOT = Path(__file__).resolve().parents[1]
APPS_ROOT = ROOT / "apps"
HTTP_FACTORY = APPS_ROOT / "configuration" / "http_client.py"
SENSITIVE_ARGUMENT_FRAGMENTS = (
    "token",
    "api_key",
    "secret",
    "password",
    "proxy",
    "credential",
)


class ArchitectureGuardTests(SimpleTestCase):
    def test_external_http_clients_are_only_created_by_proxy_factory(self) -> None:
        violations: list[str] = []
        for path in APPS_ROOT.rglob("*.py"):
            if (
                path == HTTP_FACTORY
                or "tests" in path.parts
                or "migrations" in path.parts
            ):
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            module_aliases: set[str] = set()
            constructor_aliases: set[str] = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name == "httpx":
                            module_aliases.add(alias.asname or alias.name)
                elif isinstance(node, ast.ImportFrom) and node.module == "httpx":
                    for alias in node.names:
                        if alias.name in {"Client", "AsyncClient"}:
                            constructor_aliases.add(alias.asname or alias.name)
                if not isinstance(node, ast.Call):
                    continue
                function = node.func
                if (
                    isinstance(function, ast.Attribute)
                    and isinstance(function.value, ast.Name)
                    and function.value.id in module_aliases
                    and function.attr in {"Client", "AsyncClient"}
                ):
                    violations.append(str(path.relative_to(ROOT)))
                elif (
                    isinstance(function, ast.Name)
                    and function.id in constructor_aliases
                ):
                    violations.append(str(path.relative_to(ROOT)))
        self.assertEqual(violations, [])

    def test_celery_task_signatures_do_not_accept_secrets(self) -> None:
        violations: list[str] = []
        for path in APPS_ROOT.rglob("tasks.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in tree.body:
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                is_task = any(
                    isinstance(decorator, ast.Call)
                    and getattr(decorator.func, "id", None) == "shared_task"
                    or isinstance(decorator, ast.Name)
                    and decorator.id == "shared_task"
                    for decorator in node.decorator_list
                )
                if not is_task:
                    continue
                names = [argument.arg.casefold() for argument in node.args.args]
                names.extend(
                    argument.arg.casefold() for argument in node.args.kwonlyargs
                )
                for name in names:
                    if any(
                        fragment in name for fragment in SENSITIVE_ARGUMENT_FRAGMENTS
                    ):
                        violations.append(
                            f"{path.relative_to(ROOT)}:{node.name}:{name}"
                        )
        self.assertEqual(violations, [])

    def test_compose_uses_real_read_only_master_key_and_persistent_redis(self) -> None:
        compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
        self.assertIn("file: ./docker/secrets/master.key", compose)
        self.assertNotIn("file: ./docker/secrets/master.key.example", compose)
        self.assertNotIn("mode: 0444", compose)
        self.assertIn("--appendonly", compose)
        self.assertIn("redis_data:/data", compose)
        self.assertIn("static_data:/app/staticfiles", compose)


class DeploymentGuardTests(SimpleTestCase):
    def test_ci_validates_master_key_ignore_rules_before_build(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("Validate master-key ignore rules", workflow)
        self.assertIn(
            "grep -Fxq 'docker/secrets/*.key' .gitignore",
            workflow,
        )
        self.assertIn(
            "grep -Fxq '!docker/secrets/master.key.example' .gitignore",
            workflow,
        )
        self.assertIn(
            "grep -Fxq 'docker/secrets/*.key' .dockerignore",
            workflow,
        )
        self.assertIn(
            "grep -Fxq '!docker/secrets/master.key.example' .dockerignore",
            workflow,
        )

    def test_ci_deploys_main_to_expected_directory(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("github.ref == 'refs/heads/main'", workflow)
        self.assertIn("deploy_dir=/opt/quotaradar", workflow)
        self.assertIn("sudo docker compose up -d --build --remove-orphans", workflow)
        self.assertIn("secrets.DEPLOY_HOST", workflow)
        self.assertIn("secrets.DEPLOY_PORT", workflow)
        self.assertIn("secrets.DEPLOY_USER", workflow)
        self.assertIn("secrets.DEPLOY_SSH_KEY", workflow)
        self.assertNotIn("DEPLOY_KNOWN_HOSTS", workflow)

    def test_deploy_preserves_runtime_secrets(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn('sudo cp "$deploy_dir/.env" "$release_dir/.env"', workflow)
        self.assertIn(
            '"$deploy_dir/docker/secrets/master.key"',
            workflow,
        )

    def test_ci_and_deploy_make_compose_secret_readable(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("chmod 0444 docker/secrets/master.key", workflow)
        self.assertIn(
            'sudo chmod 0444 "$release_dir/docker/secrets/master.key"',
            workflow,
        )
        self.assertNotIn(
            'sudo chmod 600 "$release_dir/docker/secrets/master.key"',
            workflow,
        )

    def test_reverse_proxy_https_settings_are_enabled(self) -> None:
        from django.conf import settings

        self.assertEqual(
            settings.SECURE_PROXY_SSL_HEADER,
            ("HTTP_X_FORWARDED_PROTO", "https"),
        )
        self.assertTrue(settings.SESSION_COOKIE_SECURE)
        self.assertTrue(settings.CSRF_COOKIE_SECURE)


class TwoFactorGuardTests(SimpleTestCase):
    """Guards against silently rolling back two-factor authentication.

    The admin is the only web-facing surface of the application, so OTP must
    stay mandatory: the admin site must require verification, OTPMiddleware
    must be wired so ``user.is_verified()`` works, and the login entrypoint
    must point at the two-factor wizard rather than the stock admin login.
    """

    def test_admin_site_requires_otp_verification(self) -> None:
        from two_factor.admin import AdminSiteOTPRequiredMixin

        from django.contrib import admin

        self.assertIsInstance(admin.site, AdminSiteOTPRequiredMixin)

    def test_otp_middleware_is_enabled(self) -> None:
        from django.conf import settings

        self.assertIn("django_otp.middleware.OTPMiddleware", settings.MIDDLEWARE)

    def test_login_routes_through_two_factor_wizard(self) -> None:
        from django.conf import settings

        self.assertEqual(settings.LOGIN_URL, "two_factor:login")
        self.assertEqual(settings.LOGIN_REDIRECT_URL, "/admin/")

    def test_totp_issuer_is_configured(self) -> None:
        from django.conf import settings

        self.assertTrue(settings.OTP_TOTP_ISSUER)

    def test_otp_apps_are_installed(self) -> None:
        from django.conf import settings

        required_apps = {
            "django_otp",
            "django_otp.plugins.otp_totp",
            "django_otp.plugins.otp_static",
            "two_factor",
            "formtools",
        }
        self.assertTrue(required_apps.issubset(set(settings.INSTALLED_APPS)))

    def test_two_factor_base_template_uses_admin_design(self) -> None:
        """Project override of two_factor/_base.html must keep the Django admin
        design instead of falling back to the package's Bootstrap CDN template.

        Guards against the reminder/banner ("Provide a template named
        two_factor/_base.html...") reappearing if the override is removed.
        """
        from django.template.loader import get_template

        template = get_template("two_factor/_base.html")
        origin = template.origin.template_name
        self.assertEqual(origin, "two_factor/_base.html")
        source = template.origin.template_source if hasattr(
            template.origin, "template_source"
        ) else Path(template.origin.name).read_text(encoding="utf-8")
        self.assertIn("admin/base_site.html", source)
        self.assertNotIn("cdnjs.cloudflare.com", source)
        self.assertNotIn("Provide a template named", source)
