from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlsplit


class UnsafeURL(ValueError):
    """Raised when a server-side fetch target is not publicly routable."""


def validate_public_url(url: str) -> None:
    parsed = urlsplit(url)
    if parsed.scheme.casefold() not in {"http", "https"} or not parsed.hostname:
        raise UnsafeURL("URL must be an absolute HTTP(S) URL")
    if parsed.username is not None or parsed.password is not None:
        raise UnsafeURL("URL-embedded credentials are not allowed")

    hostname = parsed.hostname.rstrip(".").casefold()
    if hostname == "localhost" or hostname.endswith(".localhost"):
        raise UnsafeURL("localhost targets are not allowed")

    try:
        addresses = {
            info[4][0]
            for info in socket.getaddrinfo(
                hostname,
                parsed.port or (443 if parsed.scheme.casefold() == "https" else 80),
                type=socket.SOCK_STREAM,
            )
        }
    except socket.gaierror as exc:
        raise UnsafeURL(f"hostname could not be resolved: {hostname}") from exc

    if not addresses:
        raise UnsafeURL(f"hostname resolved to no addresses: {hostname}")

    for address in addresses:
        ip = ipaddress.ip_address(address)
        if not ip.is_global:
            raise UnsafeURL(f"non-public target is not allowed: {address}")
