import socket

import pytest

from arvectum_data.acquisition.security import UnsafeURL, validate_public_url


def test_rejects_localhost_without_dns_lookup() -> None:
    with pytest.raises(UnsafeURL, match="localhost"):
        validate_public_url("http://localhost/private")


def test_rejects_private_resolved_address(monkeypatch) -> None:
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.5", 80))
        ],
    )

    with pytest.raises(UnsafeURL, match="non-public"):
        validate_public_url("http://internal.example/private")


def test_accepts_public_resolved_address(monkeypatch) -> None:
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))
        ],
    )

    validate_public_url("https://example.com/public")
