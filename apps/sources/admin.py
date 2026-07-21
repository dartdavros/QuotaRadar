"""Django Admin for X sources and ingested publications."""

from datetime import timedelta

from django.contrib import admin, messages
from django.utils import timezone
from django.utils.html import format_html

from apps.configuration.models import SystemConfiguration
from apps.monitoring.backfill_tasks import backfill_source
from apps.monitoring.dispatch import enqueue_posts_for_analysis

from .models import Source, SourcePost, SourcePostProcessingStatus


@admin.register(Source)
class SourceAdmin(admin.ModelAdmin):
    list_display = (
        "username_display",
        "provider",
        "monitoring_status",
        "x_user_id",
        "last_post_id",
        "last_checked_at",
        "last_success_at",
        "has_error",
    )
    list_filter = ("provider", "enabled")
    search_fields = ("username", "x_user_id", "last_post_id")
    actions = ("queue_historical_backfill",)
    readonly_fields = (
        "provider",
        "username",
        "x_user_id",
        "last_post_id",
        "last_checked_at",
        "last_success_at",
        "last_error",
        "monitoring_status",
    )
    fieldsets = (
        (
            "Источник",
            {"fields": ("provider", "username", "enabled")},
        ),
        (
            "Состояние X API",
            {
                "fields": (
                    "x_user_id",
                    "last_post_id",
                    "last_checked_at",
                    "last_success_at",
                    "last_error",
                    "monitoring_status",
                )
            },
        ),
    )

    def has_add_permission(self, request) -> bool:  # type: ignore[no-untyped-def]
        return False

    def has_delete_permission(self, request, obj=None) -> bool:  # type: ignore[no-untyped-def]
        return False

    @admin.action(description="Подтянуть старые посты выбранных источников")
    def queue_historical_backfill(self, request, queryset) -> None:  # type: ignore[no-untyped-def]
        queued = 0
        failed = 0
        for source in queryset.order_by("pk"):
            try:
                backfill_source.delay(source.pk)
            except Exception:
                failed += 1
            else:
                queued += 1

        if queued:
            limit = SystemConfiguration.load().historical_backfill_post_limit
            self.message_user(
                request,
                (
                    f"Задач исторического импорта поставлено в очередь: {queued}. "
                    f"Лимит на источник: {limit} постов."
                ),
                level=messages.SUCCESS,
            )
        if failed:
            self.message_user(
                request,
                f"Не удалось поставить в очередь задач: {failed}.",
                level=messages.ERROR,
            )

    @admin.display(description="Источник", ordering="username")
    def username_display(self, obj: Source) -> str:
        return f"@{obj.username}"

    @admin.display(description="Статус")
    def monitoring_status(self, obj: Source) -> str:
        configuration = SystemConfiguration.load()
        if not configuration.monitoring_enabled or not obj.enabled:
            return "Выключен"
        if obj.last_error and (
            obj.last_success_at is None
            or obj.last_checked_at is None
            or obj.last_checked_at >= obj.last_success_at
        ):
            return "Ошибка"
        stale_before = timezone.now() - timedelta(
            seconds=configuration.poll_interval_seconds * 2
        )
        if obj.last_checked_at is None or obj.last_checked_at < stale_before:
            return "Не работает"
        return "Работает"

    @admin.display(boolean=True, description="Есть ошибка")
    def has_error(self, obj: Source) -> bool:
        return bool(obj.last_error)


@admin.register(SourcePost)
class SourcePostAdmin(admin.ModelAdmin):
    list_display = (
        "external_id",
        "source",
        "published_at",
        "received_at",
        "processing_status",
        "processing_started_at",
        "source_link",
    )
    list_filter = ("source", "processing_status", "published_at", "received_at")
    search_fields = ("external_id", "text", "normalized_text", "source__username")
    date_hierarchy = "published_at"
    ordering = ("-published_at",)
    actions = ("requeue_failed_posts",)
    readonly_fields = (
        "source",
        "external_id",
        "text",
        "normalized_text",
        "source_link",
        "published_at",
        "received_at",
        "raw_data",
        "processing_status",
        "processing_started_at",
        "last_error",
    )
    fields = readonly_fields

    @admin.action(description="Вернуть выбранные ошибочные посты в очередь анализа")
    def requeue_failed_posts(self, request, queryset) -> None:  # type: ignore[no-untyped-def]
        result = enqueue_posts_for_analysis(
            post_ids=queryset.values_list("pk", flat=True),
            eligible_statuses=(SourcePostProcessingStatus.FAILED,),
        )
        if result.queued:
            self.message_user(
                request,
                f"Поставлено в очередь анализа: {result.queued}.",
                level=messages.SUCCESS,
            )
        if result.skipped:
            self.message_user(
                request,
                (
                    f"Пропущено: {result.skipped}. Вернуть в очередь можно только "
                    "посты со статусом «Ошибка»."
                ),
                level=messages.WARNING,
            )
        if result.dispatch_failed:
            self.message_user(
                request,
                f"Не удалось поставить в очередь: {result.dispatch_failed}.",
                level=messages.ERROR,
            )

    @admin.display(description="Источник")
    def source_link(self, obj: SourcePost) -> str:
        return format_html(
            '<a href="{}" target="_blank" rel="noopener noreferrer">Открыть в X</a>',
            obj.source_url,
        )

    def has_add_permission(self, request) -> bool:  # type: ignore[no-untyped-def]
        return False

    def has_change_permission(self, request, obj=None) -> bool:  # type: ignore[no-untyped-def]
        if request.method == "POST" and "action" in request.POST:
            return super().has_change_permission(request, obj)
        return request.method in {
            "GET",
            "HEAD",
            "OPTIONS",
        } and super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None) -> bool:  # type: ignore[no-untyped-def]
        return False
