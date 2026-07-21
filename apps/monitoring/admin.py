"""Read-only Django Admin journal for operational monitoring events."""

from django.contrib import admin

from .models import MonitoringEvent


@admin.register(MonitoringEvent)
class MonitoringEventAdmin(admin.ModelAdmin):
    list_display = (
        "created_at",
        "component",
        "status",
        "source",
        "message",
        "error_type",
        "task_id",
    )
    list_filter = ("component", "status", "source")
    search_fields = ("message", "error_type", "task_id", "source__username")
    readonly_fields = (
        "created_at",
        "component",
        "status",
        "source",
        "message",
        "error_type",
        "task_id",
    )
    date_hierarchy = "created_at"
    ordering = ("-created_at", "-pk")

    def has_add_permission(self, request) -> bool:  # type: ignore[no-untyped-def]
        return False

    def has_change_permission(self, request, obj=None) -> bool:  # type: ignore[no-untyped-def]
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            return False
        return super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None) -> bool:  # type: ignore[no-untyped-def]
        return False
