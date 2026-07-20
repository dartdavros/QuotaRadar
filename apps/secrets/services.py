"""Only supported application interface for reading and writing secrets."""

from __future__ import annotations

from dataclasses import dataclass

from django.contrib.auth.models import AbstractBaseUser
from django.db import transaction

from .crypto import SecretDecryptionError, decrypt_secret, encrypt_secret
from .models import EncryptedSecret, SecretCode
from .redaction import register_sensitive_value


class SecretNotConfiguredError(RuntimeError):
    """Raised when a required secret has no encrypted value."""


@dataclass(frozen=True, slots=True)
class SecretStatus:
    code: str
    configured: bool
    key_version: str | None


def normalize_secret_code(code: str | SecretCode) -> str:
    value = code.value if isinstance(code, SecretCode) else code
    valid_codes = {choice.value for choice in SecretCode}
    if value not in valid_codes:
        raise ValueError("Unknown secret code.")
    return value


def get_secret_record(code: str | SecretCode) -> EncryptedSecret:
    return EncryptedSecret.objects.get(code=normalize_secret_code(code))


def get_secret(code: str | SecretCode) -> str:
    record = get_secret_record(code)
    if not record.is_configured:
        raise SecretNotConfiguredError("Required secret is not configured.")
    value = decrypt_secret(
        code=record.code,
        encrypted_value=bytes(record.encrypted_value),
        key_version=record.key_version,
    )
    register_sensitive_value(value)
    return value


def get_optional_secret(code: str | SecretCode) -> str | None:
    try:
        return get_secret(code)
    except SecretNotConfiguredError:
        return None


@transaction.atomic
def set_secret(
    code: str | SecretCode,
    value: str,
    *,
    updated_by: AbstractBaseUser | None,
) -> EncryptedSecret:
    normalized_code = normalize_secret_code(code)
    if not value:
        raise ValueError("Secret value must not be empty.")

    payload = encrypt_secret(code=normalized_code, plaintext=value)
    record, _ = EncryptedSecret.objects.select_for_update().get_or_create(
        code=normalized_code
    )
    record.encrypted_value = payload.value
    record.key_version = payload.key_version
    record.updated_by = updated_by
    record.save(
        update_fields=("encrypted_value", "key_version", "updated_by", "updated_at")
    )
    register_sensitive_value(value)
    return record


@transaction.atomic
def clear_secret(
    code: str | SecretCode,
    *,
    updated_by: AbstractBaseUser | None,
) -> EncryptedSecret:
    record = EncryptedSecret.objects.select_for_update().get(
        code=normalize_secret_code(code)
    )
    record.encrypted_value = None
    record.key_version = ""
    record.updated_by = updated_by
    record.save(
        update_fields=("encrypted_value", "key_version", "updated_by", "updated_at")
    )
    return record


def get_secret_status(code: str | SecretCode) -> SecretStatus:
    record = get_secret_record(code)
    return SecretStatus(
        code=record.code,
        configured=record.is_configured,
        key_version=record.key_version or None,
    )


__all__ = [
    "SecretDecryptionError",
    "SecretNotConfiguredError",
    "SecretStatus",
    "clear_secret",
    "get_optional_secret",
    "get_secret",
    "get_secret_record",
    "get_secret_status",
    "set_secret",
]
