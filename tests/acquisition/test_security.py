import socket

import pytest

from arvectum_data.acquisition.security import UnsafeURL, resolve_public_url, validate_public_url


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


def test_public_resolution_prefers_ipv4_without_ignoring_ipv6(monkeypatch) -> None:
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [
            (socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("2606:2800:220:1:248:1893:25c8:1946", 443, 0, 0)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443)),
        ],
    )

    resolved = resolve_public_url("https://example.com/public")

    assert resolved.hostname == "example.com"
    assert resolved.port == 443
    assert resolved.addresses == (
        "93.184.216.34",
        "2606:2800:220:1:248:1893:25c8:1946",
    )


def test_public_resolution_rejects_mixed_public_and_private_dns(monkeypatch) -> None:
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.5", 443)),
        ],
    )

    with pytest.raises(UnsafeURL, match="non-public"):
        resolve_public_url("https://example.com/public")
