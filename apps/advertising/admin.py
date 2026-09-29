"""Advertising controls using the existing Django Admin forms and journals."""
from django.contrib import admin, messages
from django import forms
from django.urls import path, reverse

from apps.sources.models import Feed
from apps.telegram.models import DeliveryTargetType
from .models import Campaign, Placement, PlacementStatus
from .services import resolve_placement
from .admin_preview import preview_campaign


class CampaignForm(forms.ModelForm):
    class Meta:
        model = Campaign
        fields = ("target", "body", "total_posts", "enabled")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk and not self.instance.body:
            self.fields["body"].initial = (
                f"{self.instance.message} [**{self.instance.link_label}**]({self.instance.url})")
        self.fields["body"].required = True
        self.fields["body"].widget.attrs["data-preview-url"] = reverse("admin:advertising_campaign_preview")
        self.fields["body"].help_text = (
            "Несколько строк и ссылок: [**Жирная ссылка**](https://example.com). "
            "Код кастомного эмодзи: обычный эмодзи[ID]. "
            "Видимый блок с «Рекомендация:» — максимум 200 единиц UTF-16.")


@admin.register(Campaign)
class CampaignAdmin(admin.ModelAdmin):
    form = CampaignForm
    list_display = ("campaign_text", "target", "enabled", "total_posts", "sent_posts", "reserved_posts", "remaining_posts", "block_length")
    list_filter = ("enabled", "target")
    readonly_fields = ("sent_posts", "reserved_posts", "remaining_posts", "created_at")
    fields = ("target", "body", "total_posts", "enabled", *readonly_fields)

    class Media:
        js = ("advertising/preview.js",)

    def get_urls(self):
        return [path("preview/", self.admin_site.admin_view(preview_campaign),
                     name="advertising_campaign_preview"), *super().get_urls()]

    @admin.display(description="Рекомендация")
    def campaign_text(self, obj):
        return (obj.body or obj.message)[:80]

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "target":
            kwargs["queryset"] = db_field.remote_field.model.objects.filter(
                feed=Feed.QUOTA, target_type=DeliveryTargetType.CHANNEL)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    @admin.display(description="Длина рекламного блока / 200")
    def block_length(self, obj):
        return obj.block_length

    @admin.display(description="Опубликовано")
    def sent_posts(self, obj):
        return obj.sent_posts

    @admin.display(description="Зарезервировано")
    def reserved_posts(self, obj):
        return obj.reserved_posts

    @admin.display(description="Осталось опубликовать")
    def remaining_posts(self, obj):
        return obj.remaining_posts

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Placement)
class PlacementAdmin(admin.ModelAdmin):
    list_display = ("campaign", "delivery", "status", "sent_at")
    list_filter = ("status", "campaign")
    actions = ("confirm_sent", "confirm_absent")
    fields = ("campaign", "delivery", "status", "created_at", "sent_at", "frozen_text", "message_id", "telegram_message_id", "resolution_note")

    def get_readonly_fields(self, request, obj=None):
        editable = obj and obj.status == PlacementStatus.UNCERTAIN
        return tuple(field for field in self.fields if not (editable and field in ("telegram_message_id", "resolution_note")))

    @admin.display(description="Зафиксированный текст поста")
    def frozen_text(self, obj):
        return obj.delivery.rendered_text

    @admin.display(description="Telegram message ID")
    def message_id(self, obj):
        return obj.delivery.telegram_message_id or "—"

    def apply_resolution(self, request, queryset, was_sent):
        for placement in queryset:
            try:
                resolve_placement(placement.pk, was_sent=was_sent)
            except ValueError as exc:
                self.message_user(request, str(exc), messages.ERROR)
            else:
                self.log_change(request, placement, f"Проверка канала: was_sent={was_sent}")
                self.message_user(request, f"Проверка размещения {placement.pk} сохранена.", messages.SUCCESS)

    @admin.action(description="Канал проверен: пост опубликован", permissions=["change"])
    def confirm_sent(self, request, queryset):
        self.apply_resolution(request, queryset, True)

    @admin.action(description="Канал проверен: пост отсутствует", permissions=["change"])
    def confirm_absent(self, request, queryset):
        self.apply_resolution(request, queryset, False)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
