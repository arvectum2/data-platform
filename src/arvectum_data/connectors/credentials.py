from __future__ import annotations

import base64
import hashlib
import json
from collections.abc import Mapping

from cryptography.fernet import Fernet, InvalidToken


class CredentialCipher:
    def __init__(self, master_key: str, *, key_version: str = "v1") -> None:
        cleaned = master_key.strip()
        if len(cleaned) < 32:
            raise ValueError("connector credential master key must be at least 32 characters")
        version = key_version.strip()
        if not version or len(version) > 32:
            raise ValueError("connector credential key version must be between 1 and 32 characters")
        derived = hashlib.sha256(cleaned.encode("utf-8")).digest()
        self._fernet = Fernet(base64.urlsafe_b64encode(derived))
        self.key_version = version

    @staticmethod
    def _normalize(secrets: Mapping[str, str]) -> dict[str, str]:
        if not secrets or len(secrets) > 32:
            raise ValueError("connector credential secrets must contain between 1 and 32 items")
        normalized: dict[str, str] = {}
        total_chars = 0
        for raw_key, raw_value in secrets.items():
            key = str(raw_key).strip()
            value = str(raw_value)
            if not key or len(key) > 128:
                raise ValueError("connector credential secret keys must be 1..128 characters")
            if not value or len(value) > 8192:
                raise ValueError("connector credential secret values must be 1..8192 characters")
            if key in normalized:
                raise ValueError("connector credential secret keys must be unique")
            total_chars += len(key) + len(value)
            if total_chars > 65536:
                raise ValueError("connector credential payload is too large")
            normalized[key] = value
        return normalized

    def encrypt(self, secrets: Mapping[str, str]) -> str:
        normalized = self._normalize(secrets)
        payload = json.dumps(
            normalized,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return self._fernet.encrypt(payload).decode("ascii")

    def decrypt(self, ciphertext: str, *, key_version: str) -> dict[str, str]:
        if key_version != self.key_version:
            raise ValueError("connector credential key version is not available")
        try:
            payload = self._fernet.decrypt(ciphertext.encode("ascii"))
        except (InvalidToken, UnicodeEncodeError) as exc:
            raise ValueError("connector credential payload could not be decrypted") from exc
        try:
            decoded = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("connector credential payload is invalid") from exc
        if not isinstance(decoded, dict):
            raise ValueError("connector credential payload must be an object")
        return self._normalize({str(key): str(value) for key, value in decoded.items()})
