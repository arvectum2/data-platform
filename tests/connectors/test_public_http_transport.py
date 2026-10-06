from __future__ import annotations

import socket

import pytest

from arvectum_data.acquisition import AcquisitionError, AcquisitionRequest
from arvectum_data.acquisition.security import PublicURLResolution, UnsafeURL
from arvectum_data.connectors.http import PublicHTTPTransport, _FetchResult, _connect_public_socket


class FakeSocket:
    def __init__(self, family, *, fail=False):
        self.family = family
        self.fail = fail
        self.timeout = None
        self.closed = False
        self.endpoint = None

    def settimeout(self, value):
        self.timeout = value

    def connect(self, endpoint):
        self.endpoint = endpoint
        if self.fail:
            raise OSError("unreachable")

    def close(self):
        self.closed = True


def test_connect_public_socket_uses_ipv4_before_ipv6(monkeypatch) -> None:
    created = []

    def fake_socket(family, socktype):
        sock = FakeSocket(family)
        created.append(sock)
        return sock

    monkeypatch.setattr(socket, "socket", fake_socket)
    target = PublicURLResolution(
        scheme="https",
        hostname="example.com",
        port=443,
        addresses=("93.184.216.34", "2606:2800:220:1:248:1893:25c8:1946"),
    )

    connected = _connect_public_socket(target, timeout_seconds=5.0)

    assert connected is created[0]
    assert created[0].family == socket.AF_INET
    assert created[0].endpoint == ("93.184.216.34", 443)
    assert len(created) == 1


def test_connect_public_socket_falls_back_to_ipv6(monkeypatch) -> None:
    created = []

    def fake_socket(family, socktype):
        sock = FakeSocket(family, fail=(family == socket.AF_INET))
        created.append(sock)
        return sock

    monkeypatch.setattr(socket, "socket", fake_socket)
    target = PublicURLResolution(
        scheme="https",
        hostname="example.com",
        port=443,
        addresses=("93.184.216.34", "2606:2800:220:1:248:1893:25c8:1946"),
    )

    connected = _connect_public_socket(target, timeout_seconds=5.0)

    assert created[0].closed is True
    assert connected is created[1]
    assert created[1].family == socket.AF_INET6
    assert created[1].endpoint == (
        "2606:2800:220:1:248:1893:25c8:1946",
        443,
        0,
        0,
    )


def test_public_transport_rejects_sensitive_headers() -> None:
    transport = PublicHTTPTransport()

    with pytest.raises(AcquisitionError, match="rejects credential/host headers"):
        transport.fetch(
            AcquisitionRequest(
                url="https://example.com/",
                headers={"Authorization": "Bearer must-not-leave"},
            )
        )


def test_public_transport_validates_redirect_before_following(monkeypatch) -> None:
    transport = PublicHTTPTransport()
    calls = []

    def fake_resolve(url):
        calls.append(url)
        if url == "http://127.0.0.1/private":
            raise UnsafeURL("non-public target is not allowed: 127.0.0.1")
        return PublicURLResolution(
            scheme="https",
            hostname="example.com",
            port=443,
            addresses=("93.184.216.34",),
        )

    monkeypatch.setattr(
        "arvectum_data.connectors.http.resolve_public_url",
        fake_resolve,
    )
    monkeypatch.setattr(
        transport,
        "_request_once",
        lambda *args, **kwargs: _FetchResult(
            status=302,
            final_url="https://example.com/",
            content_type="text/html",
            headers={"Location": "http://127.0.0.1/private"},
            body=b"",
            location="http://127.0.0.1/private",
        ),
    )

    with pytest.raises(UnsafeURL, match="non-public"):
        transport.fetch(AcquisitionRequest(url="https://example.com/"))

    assert calls == [
        "https://example.com/",
        "http://127.0.0.1/private",
    ]
