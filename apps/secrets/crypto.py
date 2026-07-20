"""Authenticated encryption for application secrets."""

from __future__ import annotations

import os
from dataclasses import dataclass

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from django.conf import settings

from .keyring import MasterKeyError, load_master_keyring

_NONCE_SIZE = 12
_ASSOCIATED_DATA_PREFIX = "quotaradar-secret"


class SecretEncryptionError(RuntimeError):
    """Raised when a secret cannot be encrypted safely."""


class SecretDecryptionError(RuntimeError):
    """Raised when ciphertext cannot be authenticated or decrypted."""


@dataclass(frozen=True, slots=True)
class EncryptedPayload:
    value: bytes
    key_version: str


def _associated_data(*, code: str, version: str) -> bytes:
    return f"{_ASSOCIATED_DATA_PREFIX}:{code}:{version}".encode("utf-8")


def encrypt_secret(*, code: str, plaintext: str) -> EncryptedPayload:
    try:
        keyring = load_master_keyring(settings.QUOTARADAR_MASTER_KEY_FILE)
        version = keyring.active_version
        nonce = os.urandom(_NONCE_SIZE)
        ciphertext = AESGCM(keyring.derive(version)).encrypt(
            nonce,
            plaintext.encode("utf-8"),
            _associated_data(code=code, version=version),
        )
    except (MasterKeyError, UnicodeEncodeError, ValueError):
        raise SecretEncryptionError("Secret encryption failed.") from None
    return EncryptedPayload(value=nonce + ciphertext, key_version=version)


def decrypt_secret(*, code: str, encrypted_value: bytes, key_version: str) -> str:
    if len(encrypted_value) <= _NONCE_SIZE:
        raise SecretDecryptionError("Secret decryption failed.")

    try:
        keyring = load_master_keyring(settings.QUOTARADAR_MASTER_KEY_FILE)
        nonce = encrypted_value[:_NONCE_SIZE]
        ciphertext = encrypted_value[_NONCE_SIZE:]
        plaintext = AESGCM(keyring.derive(key_version)).decrypt(
            nonce,
            ciphertext,
            _associated_data(code=code, version=key_version),
        )
        return plaintext.decode("utf-8")
    except (MasterKeyError, InvalidTag, UnicodeDecodeError, ValueError):
        raise SecretDecryptionError("Secret decryption failed.") from None
