"""Permission-aware administration of encrypted application secrets."""

from __future__ import annotations

from django import forms
from django.contrib import admin
from django.http import HttpRequest

from .crypto import SecretDecryptionError
from .models import EncryptedSecret
from .services import clear_secret, get_secret, set_secret

_VIEW_VALUE_PERMISSION = "secrets.view_secret_value"
_CHANGE_VALUE_PERMISSION = "secrets.change_secret_value"


class EncryptedSecretAdminForm(forms.ModelForm):
    secret_value = forms.CharField(
        label="Расшифрованное значение",
        required=False,
        strip=False,
    )
    clear_value = forms.BooleanField(
        label="Очистить значение",
        required=False,
    )

    class Meta:
        model = EncryptedSecret
        fields: tuple[str, ...] = ()

    def clean(self) -> dict[str, object]:
        cleaned_data = super().clean()
        if cleaned_data.get("clear_value") and cleaned_data.get("secret_value"):
            raise forms.ValidationError(
                "Нельзя одновременно задать новое значение и очистить секрет."
            )
        return cleaned_data


@admin.register(EncryptedSecret)
class EncryptedSecretAdmin(admin.ModelAdmin):
    form = EncryptedSecretAdminForm
    list_display = (
        "code_label",
        "configured",
        "key_version",
        "updated_at",
        "updated_by",
    )
    readonly_fields = (
        "code",
        "configured",
        "decrypted_value",
        "hidden_value",
        "key_version",
        "updated_at",
        "updated_by",
    )
    ordering = ("code",)

    @admin.display(description="Секрет", ordering="code")
    def code_label(self, obj: EncryptedSecret) -> str:
        return obj.get_code_display()

    @admin.display(description="Расшифрованное значение")
    def decrypted_value(self, obj: EncryptedSecret) -> str:
        if not obj.is_configured:
            return "Не настроен"
        try:
            return get_secret(obj.code)
        except SecretDecryptionError:
            return "Невозможно расшифровать"

    @admin.display(description="Расшифрованное значение")
    def hidden_value(self, obj: EncryptedSecret) -> str:
        return "Нет разрешения на просмотр значения"

    def get_fields(
        self,
        request: HttpRequest,
        obj: EncryptedSecret | None = None,
    ) -> tuple[str, ...]:
        fields = ["code", "configured"]
        can_edit_value = request.user.has_perm(
            _CHANGE_VALUE_PERMISSION
        ) and super().has_change_permission(request, obj)
        if can_edit_value:
            fields.extend(("secret_value", "clear_value"))
        elif request.user.has_perm(_VIEW_VALUE_PERMISSION):
            fields.append("decrypted_value")
        else:
            fields.append("hidden_value")
        fields.extend(("key_version", "updated_at", "updated_by"))
        return tuple(fields)

    @admin.display(description="Настроен", boolean=True)
    def configured(self, obj: EncryptedSecret) -> bool:
        return obj.is_configured

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_delete_permission(
        self,
        request: HttpRequest,
        obj: EncryptedSecret | None = None,
    ) -> bool:
        return False

    def get_form(
        self,
        request: HttpRequest,
        obj: EncryptedSecret | None = None,
        change: bool = False,
        **kwargs: object,
    ) -> type[forms.ModelForm]:
        base_form = super().get_form(request, obj, change=change, **kwargs)
        can_view_value = request.user.has_perm(_VIEW_VALUE_PERMISSION)
        can_change_value = request.user.has_perm(_CHANGE_VALUE_PERMISSION)

        class RequestBoundSecretForm(base_form):  # type: ignore[misc,valid-type]
            def __init__(self, *args: object, **form_kwargs: object) -> None:
                super().__init__(*args, **form_kwargs)
                value_field = self.fields.get("secret_value")
                clear_field = self.fields.get("clear_value")

                if not can_view_value and not can_change_value:
                    if value_field is not None:
                        value_field.disabled = True
                        value_field.widget = forms.PasswordInput(render_value=False)
                        value_field.help_text = "Нет разрешения на просмотр значения."
                    if clear_field is not None:
                        clear_field.disabled = True
                    return

                if value_field is not None:
                    if can_view_value and obj and obj.is_configured:
                        try:
                            value_field.initial = get_secret(obj.code)
                            value_field.widget = forms.TextInput()
                        except SecretDecryptionError:
                            value_field.initial = ""
                            value_field.help_text = (
                                "Текущее значение невозможно расшифровать. "
                                "Его можно заменить новым значением."
                            )
                    else:
                        value_field.widget = forms.PasswordInput(render_value=False)
                        if obj and obj.is_configured:
                            value_field.help_text = "Текущее значение скрыто. Введите новое значение только для замены."
                    value_field.disabled = not can_change_value

                if clear_field is not None:
                    clear_field.disabled = not can_change_value

        return RequestBoundSecretForm

    def save_model(
        self,
        request: HttpRequest,
        obj: EncryptedSecret,
        form: forms.ModelForm,
        change: bool,
    ) -> None:
        super().save_model(request, obj, form, change)
        if not request.user.has_perm(_CHANGE_VALUE_PERMISSION):
            return

        if form.cleaned_data.get("clear_value"):
            clear_secret(obj.code, updated_by=request.user)
            return

        if "secret_value" in form.changed_data:
            value = form.cleaned_data.get("secret_value")
            if isinstance(value, str) and value:
                set_secret(obj.code, value, updated_by=request.user)
