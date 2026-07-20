"""Run credential-safe diagnostics for database-backed configuration."""

from django.core.management.base import BaseCommand, CommandError

from apps.configuration.diagnostics import collect_diagnostics


class Command(BaseCommand):
    help = "Check runtime configuration and optionally test external proxy access."

    def add_arguments(self, parser) -> None:  # type: ignore[no-untyped-def]
        parser.add_argument(
            "--test-proxy",
            action="store_true",
            help="Perform a HEAD request to the test URL through the configured proxy.",
        )
        parser.add_argument(
            "--test-url",
            default="https://example.com/",
            help="External URL used only with --test-proxy.",
        )

    def handle(self, *args: object, **options: object) -> None:
        results = collect_diagnostics(
            test_proxy=bool(options["test_proxy"]),
            test_url=str(options["test_url"]),
        )
        has_errors = False
        for result in results:
            line = f"[{result.status.upper()}] {result.name}: {result.detail}"
            if result.status == "ok":
                self.stdout.write(self.style.SUCCESS(line))
            elif result.status == "warning":
                self.stdout.write(self.style.WARNING(line))
            else:
                has_errors = True
                self.stderr.write(self.style.ERROR(line))

        if has_errors:
            raise CommandError("Runtime configuration diagnostics failed.")
