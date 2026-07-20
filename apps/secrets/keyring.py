"""Master-key loading and versioned key derivation."""

from __future__ import annotations

import base64
import binascii
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

_KEY_CONTEXT = b"quotaradar/encrypted-secrets/v1"


class MasterKeyError(RuntimeError):
    """Raised when the configured master-key file is unavailable or invalid."""


@dataclass(frozen=True, slots=True)
class MasterKeyRing:
    active_version: str
    keys: dict[str, bytes]

    def derive(self, version: str) -> bytes:
        material = self.keys.get(version)
        if material is None:
            raise MasterKeyError("Required master-key version is not available.")
        return HKDF(
            algorithm=hashes.SHA256(),
            length=32,
            salt=_KEY_CONTEXT,
            info=version.encode("utf-8"),
        ).derive(material)


def _decode_material(value: Any) -> bytes:
    if not isinstance(value, str) or not value:
        raise MasterKeyError("Master-key material is invalid.")
    if value.startswith("base64:"):
        try:
            decoded = base64.urlsafe_b64decode(value.removeprefix("base64:").encode())
        except (ValueError, binascii.Error) as exc:
            raise MasterKeyError("Master-key material is invalid.") from exc
        if not decoded:
            raise MasterKeyError("Master-key material is invalid.")
        return decoded
    return value.encode("utf-8")


def _parse_json_keyring(raw: bytes) -> MasterKeyRing:
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MasterKeyError("Master-key file is invalid.") from exc

    if not isinstance(payload, dict):
        raise MasterKeyError("Master-key file is invalid.")
    active_version = payload.get("active_version")
    raw_keys = payload.get("keys")
    if not isinstance(active_version, str) or not active_version:
        raise MasterKeyError("Master-key file is invalid.")
    if not isinstance(raw_keys, dict) or not raw_keys:
        raise MasterKeyError("Master-key file is invalid.")

    keys = {
        str(version): _decode_material(material)
        for version, material in raw_keys.items()
        if isinstance(version, str) and version
    }
    if active_version not in keys:
        raise MasterKeyError("Active master-key version is not available.")
    return MasterKeyRing(active_version=active_version, keys=keys)


def load_master_keyring(path: Path) -> MasterKeyRing:
    """Load a versioned JSON keyring or a legacy single-key file."""

    try:
        raw = path.read_bytes().strip()
    except OSError as exc:
        raise MasterKeyError("Master-key file cannot be read.") from exc

    if not raw:
        raise MasterKeyError("Master-key file is empty.")
    if raw.startswith(b"{"):
        return _parse_json_keyring(raw)
    return MasterKeyRing(active_version="v1", keys={"v1": raw})
