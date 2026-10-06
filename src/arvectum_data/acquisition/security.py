from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import urlsplit


class UnsafeURL(ValueError):
    """Raised when a server-side fetch target is not publicly routable."""


@dataclass(frozen=True, slots=True)
class PublicURLResolution:
    scheme: str
    hostname: str
    port: int
    addresses: tuple[str, ...]


def resolve_public_url(url: str) -> PublicURLResolution:
    parsed = urlsplit(url)
    scheme = parsed.scheme.casefold()
    if scheme not in {"http", "https"} or not parsed.hostname:
        raise UnsafeURL("URL must be an absolute HTTP(S) URL")
    if parsed.username is not None or parsed.password is not None:
        raise UnsafeURL("URL-embedded credentials are not allowed")

    hostname = parsed.hostname.rstrip(".").casefold()
    if hostname == "localhost" or hostname.endswith(".localhost"):
        raise UnsafeURL("localhost targets are not allowed")
    port = parsed.port or (443 if scheme == "https" else 80)

    try:
        infos = socket.getaddrinfo(
            hostname,
            port,
            type=socket.SOCK_STREAM,
        )
    except socket.gaierror as exc:
        raise UnsafeURL(f"hostname could not be resolved: {hostname}") from exc

    addresses: list[str] = []
    seen: set[str] = set()
    for info in infos:
        address = str(info[4][0])
        if address in seen:
            continue
        seen.add(address)
        ip = ipaddress.ip_address(address)
        if not ip.is_global:
            raise UnsafeURL(f"non-public target is not allowed: {address}")
        addresses.append(address)

    if not addresses:
        raise UnsafeURL(f"hostname resolved to no addresses: {hostname}")

    # Prefer IPv4 on dual-stack hosts. Some macOS networks expose a global IPv6
    # route in DNS but have no working IPv6 path, which otherwise burns the full
    # socket timeout before falling back to IPv4.
    addresses.sort(key=lambda value: 0 if ipaddress.ip_address(value).version == 4 else 1)
    return PublicURLResolution(
        scheme=scheme,
        hostname=hostname,
        port=port,
        addresses=tuple(addresses),
    )


def validate_public_url(url: str) -> None:
    resolve_public_url(url)
