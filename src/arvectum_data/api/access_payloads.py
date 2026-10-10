"""Side-effect-free, credential-safe API response projection and metadata validation.

This module must never serialize connector secrets or API-key hashes.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..storage.postgres import ConsumerApiKeyRow, ConnectorCredentialRow


def _consumer_key_payload(row: ConsumerApiKeyRow) -> dict[str, Any]:
    return {
        "key_id": row.key_id,
        "consumer_id": row.consumer_id,
        "tenant_id": row.tenant_id,
        "key_prefix": row.key_prefix,
        "label": row.label,
        "status": row.status,
        "created_at": row.created_at,
        "expires_at": row.expires_at,
        "revoked_at": row.revoked_at,
    }

def _connector_credential_payload(row: ConnectorCredentialRow) -> dict[str, Any]:
    return {
        "credential_id": row.credential_id,
        "tenant_id": row.tenant_id,
        "consumer_id": row.consumer_id,
        "connector": row.connector_name,
        "label": row.label,
        "status": row.status,
        "metadata": dict(row.metadata_json or {}),
        "created_at": row.created_at,
        "revoked_at": row.revoked_at,
    }

def _normalize_credential_metadata(
    metadata: Mapping[str, object] | None,
) -> dict[str, object]:
    result = dict(metadata or {})
    if len(result) > 32:
        raise ValueError("connector credential metadata may contain at most 32 keys")
    blocked_fragments = (
        "secret",
        "password",
        "token",
        "api_key",
        "apikey",
        "authorization",
    )
    for key, value in result.items():
        normalized_key = str(key).strip()
        if not normalized_key or len(normalized_key) > 128:
            raise ValueError("connector credential metadata keys must be 1..128 characters")
        lowered_key = normalized_key.casefold()
        if any(fragment in lowered_key for fragment in blocked_fragments):
            raise ValueError("sensitive connector credential values must be stored in secrets")
        if isinstance(value, (dict, list, tuple, set)):
            raise ValueError("connector credential metadata must contain scalar values only")
        if value is not None and len(str(value)) > 1024:
            raise ValueError("connector credential metadata values are too large")
    return result
