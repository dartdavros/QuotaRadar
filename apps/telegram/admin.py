"""Django Admin for Telegram recipients and delivery history."""

from django.contrib import admin, messages

from .models import Delivery, DeliveryTarget
from .services import requeue_failed_deliveries


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
    actions = ("requeue_failed_deliveries",)
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

    @admin.action(description="Вернуть выбранные ошибочные доставки в очередь")
    def requeue_failed_deliveries(self, request, queryset) -> None:  # type: ignore[no-untyped-def]
        result = requeue_failed_deliveries(
            delivery_ids=queryset.values_list("pk", flat=True),
        )
        if result.queued:
            self.message_user(
                request,
                f"Поставлено в очередь Telegram: {result.queued}.",
                level=messages.SUCCESS,
            )
        if result.skipped:
            self.message_user(
                request,
                (
                    f"Пропущено: {result.skipped}. Вернуть в очередь можно только "
                    "доставки со статусом «Ошибка»."
                ),
                level=messages.WARNING,
            )
        if result.dispatch_failed:
            self.message_user(
                request,
                f"Не удалось поставить в очередь: {result.dispatch_failed}.",
                level=messages.ERROR,
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
