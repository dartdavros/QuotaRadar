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
        self.assertIn("mode: 0444", compose)
        self.assertIn("--appendonly", compose)
        self.assertIn("redis_data:/data", compose)
        self.assertIn("static_data:/app/staticfiles", compose)

    def test_real_master_key_is_excluded_from_git_and_docker_context(self) -> None:
        gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
        dockerignore = (ROOT / ".dockerignore").read_text(encoding="utf-8")
        self.assertIn("docker/secrets/*.key", gitignore)
        self.assertIn("docker/secrets/*.key", dockerignore)
        self.assertIn("!docker/secrets/master.key.example", gitignore)
        self.assertIn("!docker/secrets/master.key.example", dockerignore)


class DeploymentGuardTests(SimpleTestCase):
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

    def test_reverse_proxy_https_settings_are_enabled(self) -> None:
        from django.conf import settings

        self.assertEqual(
            settings.SECURE_PROXY_SSL_HEADER,
            ("HTTP_X_FORWARDED_PROTO", "https"),
        )
        self.assertTrue(settings.SESSION_COOKIE_SECURE)
        self.assertTrue(settings.CSRF_COOKIE_SECURE)
