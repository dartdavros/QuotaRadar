"""Check PostgreSQL, Redis and master-key availability."""

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.configuration.dependencies import DependencyCheckError, check_dependencies


class Command(BaseCommand):
    help = "Check PostgreSQL, Redis and master-key bootstrap dependencies."

    def handle(self, *args: object, **options: object) -> None:
        try:
            status = check_dependencies(
                redis_url=settings.REDIS_URL,
                master_key_file=settings.QUOTARADAR_MASTER_KEY_FILE,
            )
        except DependencyCheckError as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(
            self.style.SUCCESS(
                "Bootstrap dependencies are available "
                f"(database={status.database}, redis={status.redis}, "
                f"master_key={status.master_key})."
            )
        )
