"""Django Admin for Telegram recipients and delivery history."""

from django.contrib import admin

from .models import Delivery, DeliveryTarget


@admin.register(DeliveryTarget)
class DeliveryTargetAdmin(admin.ModelAdmin):
    list_display = (
        "telegram_chat_id",
        "target_type",
        "enabled",
        "created_at",
        "updated_at",
    )
    list_filter = ("target_type", "enabled")
    search_fields = ("telegram_chat_id",)
    readonly_fields = ("created_at", "updated_at")
    ordering = ("target_type", "telegram_chat_id")


@admin.register(Delivery)
class DeliveryAdmin(admin.ModelAdmin):
    list_display = (
        "analysis",
        "target",
        "status",
        "attempts",
        "telegram_message_id",
        "last_attempt_at",
        "next_attempt_at",
        "sent_at",
    )
    list_filter = ("status", "target__target_type", "sent_at", "created_at")
    search_fields = (
        "analysis__source_post__external_id",
        "target__telegram_chat_id",
        "telegram_message_id",
    )
    readonly_fields = (
        "analysis",
        "target",
        "status",
        "telegram_message_id",
        "attempts",
        "created_at",
        "updated_at",
        "last_attempt_at",
        "next_attempt_at",
        "sent_at",
        "last_error",
    )
    fields = readonly_fields

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
