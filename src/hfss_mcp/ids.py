"""Stable ID helpers for runs, trials, jobs, and manifests."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from typing import Any

_CANONICAL_SEP = (",", ":")


def new_id(prefix: str = "") -> str:
    """Return a new opaque identifier, optionally prefixed."""
    token = uuid.uuid4().hex
    return f"{prefix}{token}" if prefix else token


def sha256_hex(data: bytes | str) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def file_sha256(path: Any) -> str:
    """Hash a file in chunks; ``path`` must be a Path-like."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def canonical_json_bytes(value: Any) -> bytes:
    """RFC-ish stable JSON: sorted keys, no insignificant whitespace, UTF-8."""
    return json.dumps(
        value,
        sort_keys=True,
        separators=_CANONICAL_SEP,
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def canonical_json_hash(value: Any) -> str:
    return sha256_hex(canonical_json_bytes(value))


_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")


def require_safe_id(value: str, *, field: str) -> str:
    text = value.strip()
    if not _SAFE_ID_RE.match(text):
        raise ValueError(f"{field} must be a short safe identifier, got {value!r}")
    return text
