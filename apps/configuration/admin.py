"""Django Admin configuration for runtime settings and prompts."""

from django.contrib import admin

from .models import PromptTemplate, SystemConfiguration


@admin.register(PromptTemplate)
class PromptTemplateAdmin(admin.ModelAdmin):
    list_display = ("code", "version", "is_active", "created_at")
    list_filter = ("code", "is_active")
    search_fields = ("code",)
    readonly_fields = ("created_at",)
    ordering = ("code", "-version")


@admin.register(SystemConfiguration)
class SystemConfigurationAdmin(admin.ModelAdmin):
    list_display = (
        "monitoring_enabled",
        "poll_interval_seconds",
        "bootstrap_post_limit",
        "regular_poll_post_limit",
        "historical_backfill_post_limit",
        "telegram_message_timezone",
        "llm_provider",
        "llm_model",
        "active_prompt",
    )
    fieldsets = (
        (
            "Мониторинг",
            {
                "fields": (
                    "monitoring_enabled",
                    "poll_interval_seconds",
                    "bootstrap_post_limit",
                    "regular_poll_post_limit",
                    "historical_backfill_post_limit",
                )
            },
        ),
        (
            "Telegram",
            {"fields": ("telegram_message_timezone",)},
        ),
        (
            "ИИ-провайдер",
            {
                "fields": (
                    "llm_provider",
                    "llm_base_url",
                    "llm_model",
                    "llm_temperature",
                    "llm_max_tokens",
                    "llm_timeout_seconds",
                    "retry_count",
                    "active_prompt",
                )
            },
        ),
    )

    def has_add_permission(self, request) -> bool:  # type: ignore[no-untyped-def]
        return not SystemConfiguration.objects.exists() and super().has_add_permission(
            request
        )

    def has_delete_permission(self, request, obj=None) -> bool:  # type: ignore[no-untyped-def]
        return False
