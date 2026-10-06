from __future__ import annotations

import pytest

from arvectum_data.connectors import CredentialCipher


def test_credential_cipher_round_trip_does_not_expose_plaintext() -> None:
    cipher = CredentialCipher("x" * 48, key_version="v1")
    encrypted = cipher.encrypt(
        {
            "api_key": "super-secret-token",
            "username": "customer@example.com",
        }
    )

    assert "super-secret-token" not in encrypted
    assert "customer@example.com" not in encrypted
    assert cipher.decrypt(encrypted, key_version="v1") == {
        "api_key": "super-secret-token",
        "username": "customer@example.com",
    }


def test_credential_cipher_rejects_wrong_key_version() -> None:
    cipher = CredentialCipher("x" * 48, key_version="v2")
    encrypted = cipher.encrypt({"token": "secret"})

    with pytest.raises(ValueError, match="key version"):
        cipher.decrypt(encrypted, key_version="v1")


def test_credential_cipher_rejects_short_master_key() -> None:
    with pytest.raises(ValueError, match="at least 32"):
        CredentialCipher("too-short")


def test_credential_cipher_rejects_oversized_or_empty_secret_payloads() -> None:
    cipher = CredentialCipher("y" * 48)

    with pytest.raises(ValueError, match="between 1 and 32"):
        cipher.encrypt({})
    with pytest.raises(ValueError, match="1..8192"):
        cipher.encrypt({"token": ""})
