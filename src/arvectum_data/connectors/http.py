from __future__ import annotations

import http.client
import ipaddress
import socket
import ssl
import time
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

from ..acquisition import AcquisitionError, AcquisitionRequest, PageSnapshot
from ..acquisition.security import PublicURLResolution, resolve_public_url


_DEFAULT_USER_AGENT = "ArvectumDataPlatform/0.3 (+https://arvectum.com)"
_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
_SENSITIVE_PUBLIC_HEADERS = frozenset(
    {"authorization", "proxy-authorization", "cookie", "host"}
)


@dataclass(frozen=True, slots=True)
class _FetchResult:
    status: int
    final_url: str
    content_type: str
    headers: dict[str, str]
    body: bytes
    location: str | None = None


def _connect_public_socket(
    target: PublicURLResolution,
    *,
    timeout_seconds: float,
) -> socket.socket:
    deadline = time.monotonic() + timeout_seconds
    errors: list[str] = []
    total = len(target.addresses)

    for index, address in enumerate(target.addresses):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break

        # On dual-stack hosts fail over quickly between address families rather
        # than spending the whole request timeout on the first unreachable IP.
        connect_timeout = remaining
        if total > 1 and index < total - 1:
            connect_timeout = min(2.0, remaining)

        ip = ipaddress.ip_address(address)
        family = socket.AF_INET if ip.version == 4 else socket.AF_INET6
        sock = socket.socket(family, socket.SOCK_STREAM)
        try:
            sock.settimeout(connect_timeout)
            endpoint = (
                (address, target.port)
                if family == socket.AF_INET
                else (address, target.port, 0, 0)
            )
            sock.connect(endpoint)
            sock.settimeout(timeout_seconds)
            return sock
        except OSError as exc:
            errors.append(f"{address}:{type(exc).__name__}")
            sock.close()

    detail = ",".join(errors) if errors else "timeout"
    raise AcquisitionError(
        f"public HTTP connection failed for {target.hostname}:{target.port}: {detail}"
    )


class PublicHTTPTransport:
    name = "public_http"

    def __init__(self, *, max_redirects: int = 5) -> None:
        if max_redirects < 0 or max_redirects > 20:
            raise ValueError("max_redirects must be between 0 and 20")
        self.max_redirects = max_redirects

    def fetch(self, request: AcquisitionRequest) -> PageSnapshot:
        headers = {"User-Agent": _DEFAULT_USER_AGENT, **dict(request.headers)}
        sensitive = sorted(
            key
            for key in headers
            if key.casefold() in _SENSITIVE_PUBLIC_HEADERS
        )
        if sensitive:
            raise AcquisitionError(
                "public HTTP transport rejects credential/host headers: "
                + ",".join(sensitive)
            )

        current_url = request.url
        redirects = 0
        while True:
            target = resolve_public_url(current_url)
            try:
                result = self._request_once(
                    current_url,
                    target,
                    headers=headers,
                    timeout_seconds=request.timeout_s,
                    max_bytes=request.max_bytes,
                )
            except AcquisitionError:
                raise
            except Exception as exc:
                raise AcquisitionError(
                    f"public HTTP transport failed for {current_url}: {exc}"
                ) from exc

            if result.status not in _REDIRECT_STATUSES or not result.location:
                if result.status >= 400:
                    raise AcquisitionError(
                        f"HTTP status {result.status} for {current_url}"
                    )
                return PageSnapshot(
                    requested_url=request.url,
                    final_url=result.final_url,
                    status_code=result.status,
                    content_type=result.content_type,
                    body=result.body,
                    headers=result.headers,
                    rendered=False,
                )

            if redirects >= self.max_redirects:
                raise AcquisitionError(
                    f"public HTTP redirect limit exceeded for {request.url}"
                )
            redirects += 1
            current_url = urljoin(current_url, result.location)

    def _request_once(
        self,
        url: str,
        target: PublicURLResolution,
        *,
        headers: dict[str, str],
        timeout_seconds: float,
        max_bytes: int,
    ) -> _FetchResult:
        parsed = urlsplit(url)
        path = parsed.path or "/"
        if parsed.query:
            path = f"{path}?{parsed.query}"

        sock = _connect_public_socket(
            target,
            timeout_seconds=timeout_seconds,
        )
        connection: http.client.HTTPConnection
        try:
            if target.scheme == "https":
                context = ssl.create_default_context()
                wrapped = context.wrap_socket(
                    sock,
                    server_hostname=target.hostname,
                )
                connection = http.client.HTTPSConnection(
                    target.hostname,
                    target.port,
                    timeout=timeout_seconds,
                    context=context,
                )
                connection.sock = wrapped
            else:
                connection = http.client.HTTPConnection(
                    target.hostname,
                    target.port,
                    timeout=timeout_seconds,
                )
                connection.sock = sock

            connection.request("GET", path, headers=headers)
            response = connection.getresponse()
            status = int(response.status)
            response_headers = {
                key: value
                for key, value in response.getheaders()
            }
            content_type = (
                response.getheader("Content-Type")
                or "application/octet-stream"
            )
            location = response.getheader("Location")
            body = response.read(max_bytes + 1)
            if len(body) > max_bytes:
                raise AcquisitionError(
                    f"HTTP response exceeds max_bytes={max_bytes} for {url}"
                )
            return _FetchResult(
                status=status,
                final_url=url,
                content_type=content_type,
                headers=response_headers,
                body=body,
                location=location,
            )
        finally:
            try:
                connection.close()
            except UnboundLocalError:
                sock.close()
