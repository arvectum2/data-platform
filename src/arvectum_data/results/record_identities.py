"""Pure durable identity codec for revisioned record sets.

Keep the storage prefixes stable across releases and SDK/API consumers.
"""

from __future__ import annotations

import base64

from .models import ResultIntegrityError


_RECORD_PREFIX = "__dp_record_v1__:"
_SET_PREFIX = "__dp_record_set_v1__:"


def _b64(value: str) -> str:
    return base64.urlsafe_b64encode(value.encode("utf-8")).decode("ascii").rstrip("=")


def _unb64(value: str) -> str:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode((value + padding).encode("ascii")).decode("utf-8")


def record_storage_item_id(item_id: str, record_id: str) -> str:
    if not item_id.strip() or not record_id.strip():
        raise ValueError("item_id and record_id must not be blank")
    return f"{_RECORD_PREFIX}{_b64(item_id)}:{_b64(record_id)}"


def record_set_storage_item_id(item_id: str) -> str:
    if not item_id.strip():
        raise ValueError("item_id must not be blank")
    return f"{_SET_PREFIX}{_b64(item_id)}"


def parse_record_storage_item_id(storage_item_id: str) -> tuple[str, str] | None:
    if not storage_item_id.startswith(_RECORD_PREFIX):
        return None
    encoded = storage_item_id[len(_RECORD_PREFIX) :]
    parts = encoded.split(":", 1)
    if len(parts) != 2:
        raise ResultIntegrityError("Malformed durable record storage item id")
    try:
        return _unb64(parts[0]), _unb64(parts[1])
    except Exception as exc:
        raise ResultIntegrityError("Malformed durable record storage identity") from exc
