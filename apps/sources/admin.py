"""Django Admin for X sources and ingested publications."""

from django.contrib import admin
from django.utils.html import format_html

from .models import Source, SourcePost


@admin.register(Source)
class SourceAdmin(admin.ModelAdmin):
    list_display = (
        "username_display",
        "provider",
        "enabled",
        "x_user_id",
        "last_post_id",
        "last_checked_at",
        "last_success_at",
        "has_error",
    )
    list_filter = ("provider", "enabled")
    search_fields = ("username", "x_user_id", "last_post_id")
    readonly_fields = (
        "provider",
        "username",
        "x_user_id",
        "last_post_id",
        "last_checked_at",
        "last_success_at",
        "last_error",
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
                )
            },
        ),
    )

    def has_add_permission(self, request) -> bool:  # type: ignore[no-untyped-def]
        return False

    def has_delete_permission(self, request, obj=None) -> bool:  # type: ignore[no-untyped-def]
        return False

    @admin.display(description="Источник", ordering="username")
    def username_display(self, obj: Source) -> str:
        return f"@{obj.username}"

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

    @admin.display(description="Источник")
    def source_link(self, obj: SourcePost) -> str:
        return format_html(
            '<a href="{}" target="_blank" rel="noopener noreferrer">Открыть в X</a>',
            obj.source_url,
        )

    def has_add_permission(self, request) -> bool:  # type: ignore[no-untyped-def]
        return False

    def has_change_permission(self, request, obj=None) -> bool:  # type: ignore[no-untyped-def]
        return request.method in {
            "GET",
            "HEAD",
            "OPTIONS",
        } and super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None) -> bool:  # type: ignore[no-untyped-def]
        return False
