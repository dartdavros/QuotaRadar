"""News configuration and journals within the existing Django Admin."""
from django.contrib import admin, messages
from django import forms
from django.core.exceptions import ValidationError
from .errors import NewsPolicyError
from .initial_fill import start_fill
from apps.sources.models import SourceSubscription
from .models import (NewsConfiguration, NewsAssessment, NewsEvent, NewsPublication, NewsDelivery,
                     CollectionCheckpoint, XBudgetPeriod, XApiUsage, MediaAsset, InitialFill, InitialFillSource)
from .sending import resolve

@admin.register(SourceSubscription)
class SourceSubscriptionAdmin(admin.ModelAdmin):
    list_display = ("source", "feed", "enabled", "priority", "query_terms")
    list_filter = ("feed", "enabled", "priority")
    list_select_related = ("source",)
    def has_delete_permission(self, request, obj=None):
        return False

@admin.register(NewsConfiguration)
class NewsConfigurationAdmin(admin.ModelAdmin):
    readonly_fields = ("activated_at",)
    actions = ("initial_fill",)

    @admin.action(description="Первично наполнить канал: 3 дня, X до $2", permissions=["change"])
    def initial_fill(self, request, queryset):
        if queryset.count() != 1:
            self.message_user(request, "Выберите одну запись настроек.", messages.ERROR)
            return
        try:
            run = start_fill()
        except (NewsPolicyError, ValidationError) as exc:
            self.message_user(request, str(exc), messages.ERROR)
        else:
            self.log_change(request, queryset.get(), f"Первичное наполнение {run.pk}, X до $2.")
            self.message_user(request, "Первичное наполнение поставлено в очередь.", messages.SUCCESS)
    def has_add_permission(self, request):
        return False
    def has_delete_permission(self, request, obj=None):
        return False
    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "target":
            kwargs["queryset"] = db_field.remote_field.model.objects.filter(feed="news", target_type="channel")
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

class JournalAdmin(admin.ModelAdmin):
    def get_readonly_fields(self, request, obj=None):
        return tuple(field.name for field in self.model._meta.fields)
    def has_add_permission(self, request):
        return False
    def has_delete_permission(self, request, obj=None):
        return False

@admin.register(NewsAssessment)
class AssessmentAdmin(JournalAdmin):
    list_display = ("post", "status", "attempts", "created_at")
    list_filter = ("status",)
    list_select_related = ("post", "post__source")

@admin.register(NewsEvent)
class EventAdmin(JournalAdmin):
    list_display = ("product", "version", "event_type", "score", "urgent", "expires_at")
    list_filter = ("urgent", "event_type")

@admin.register(NewsPublication)
class PublicationAdmin(JournalAdmin):
    list_display = ("id", "title", "status", "urgent", "slot_date", "created_at")
    list_filter = ("status", "urgent")

class ReceiptForm(forms.ModelForm):
    class Meta:
        model = NewsDelivery
        fields = ("message_ids", "resolution_note")
    def clean_message_ids(self):
        value = self.cleaned_data["message_ids"]
        if not isinstance(value, list) or any(not str(v).isdigit() for v in value):
            raise forms.ValidationError("Укажите список числовых ID сообщений.")
        return [str(v) for v in value]

@admin.register(NewsDelivery)
class DeliveryAdmin(JournalAdmin):
    form = ReceiptForm
    list_display = ("publication", "attempts", "sent_at", "last_error")
    actions = ("confirm_sent", "confirm_absent")
    def get_readonly_fields(self, request, obj=None):
        editable = {"message_ids", "resolution_note"} if obj and obj.publication.status == "uncertain" else set()
        return tuple(field.name for field in self.model._meta.fields if field.name not in editable)
    def apply_resolution(self, request, queryset, was_sent):
        for receipt in queryset:
            try:
                resolve(receipt.pk, was_sent=was_sent, note=receipt.resolution_note)
            except ValueError as exc:
                self.message_user(request, str(exc), messages.ERROR)
            else:
                self.log_change(request, receipt, f"Проверка канала: was_sent={was_sent}; {receipt.resolution_note}")
                self.message_user(request, f"Проверка доставки {receipt.pk} сохранена.", messages.SUCCESS)
    @admin.action(description="Канал проверен: сообщения отправлены", permissions=["change"])
    def confirm_sent(self, request, queryset):
        self.apply_resolution(request, queryset, True)
    @admin.action(description="Канал проверен: сообщения отсутствуют, разрешить повтор", permissions=["change"])
    def confirm_absent(self, request, queryset):
        self.apply_resolution(request, queryset, False)

@admin.register(CollectionCheckpoint)
class CheckpointAdmin(JournalAdmin):
    list_display = ("source", "completed_until", "next_attempt_at", "last_error")

@admin.register(XBudgetPeriod)
class BudgetAdmin(JournalAdmin):
    list_display = ("week", "limit", "committed")

@admin.register(XApiUsage)
class UsageAdmin(JournalAdmin):
    list_display = ("source", "operation", "status", "reserved", "charged_estimate", "created_at")
    list_filter = ("status",)

@admin.register(MediaAsset)
class MediaAdmin(JournalAdmin):
    list_display = ("publication", "kind", "size", "checksum")


@admin.register(InitialFill)
class InitialFillAdmin(JournalAdmin):
    list_display = ("target", "status", "window_start", "window_end", "committed", "expires_at")
    list_filter = ("status",)
    list_select_related = ("target",)


@admin.register(InitialFillSource)
class InitialFillSourceAdmin(JournalAdmin):
    list_display = ("run", "subscription", "done", "attempts", "checked_at", "last_error")
    list_filter = ("done",)
