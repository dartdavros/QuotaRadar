#!/usr/bin/env python3
"""Generate a versioned QuotaRadar master-key file without overwriting it."""

from __future__ import annotations

import argparse
import base64
import json
import os
import secrets
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("docker/secrets/master.key"),
        help="Destination path (default: docker/secrets/master.key).",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    output: Path = args.output
    output.parent.mkdir(parents=True, exist_ok=True)

    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    try:
        descriptor = os.open(output, flags, 0o600)
    except FileExistsError:
        raise SystemExit(f"Refusing to overwrite existing master key: {output}")

    material = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode("ascii")
    payload = {
        "active_version": "v1",
        "keys": {"v1": f"base64:{material}"},
    }
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=True, indent=2)
            handle.write("\n")
        try:
            output.chmod(0o600)
        except OSError:
            pass
    except Exception:
        output.unlink(missing_ok=True)
        raise

    print(f"Master key created: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
