"""Read-only Django Admin for persisted LLM analyses."""

from django.contrib import admin
from django.utils.html import format_html

from .models import Analysis


@admin.register(Analysis)
class AnalysisAdmin(admin.ModelAdmin):
    list_display = (
        "source_post",
        "is_relevant",
        "event_type",
        "provider",
        "product",
        "model",
        "prompt_version",
        "created_at",
        "has_error",
    )
    list_filter = (
        "is_relevant",
        "event_type",
        "provider",
        "product",
        "model",
        "prompt_version",
        "created_at",
    )
    search_fields = (
        "source_post__external_id",
        "source_post__source__username",
        "title_ru",
        "message_ru",
        "error",
    )
    date_hierarchy = "created_at"
    readonly_fields = (
        "source_post",
        "source_link",
        "is_relevant",
        "event_type",
        "provider",
        "product",
        "title_ru",
        "message_ru",
        "model",
        "prompt_version",
        "raw_response",
        "error",
        "created_at",
        "updated_at",
    )
    fields = readonly_fields

    @admin.display(description="Источник")
    def source_link(self, obj: Analysis) -> str:
        return format_html(
            '<a href="{}" target="_blank" rel="noopener noreferrer">Открыть в X</a>',
            obj.source_post.source_url,
        )

    @admin.display(boolean=True, description="Есть ошибка")
    def has_error(self, obj: Analysis) -> bool:
        return bool(obj.error)

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
