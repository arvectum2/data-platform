from __future__ import annotations

from urllib.request import HTTPRedirectHandler, Request, build_opener

from ..acquisition import AcquisitionError, AcquisitionRequest, PageSnapshot
from ..acquisition.security import validate_public_url


_DEFAULT_USER_AGENT = "ArvectumDataPlatform/0.3 (+https://arvectum.com)"


class _PublicRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        validate_public_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class PublicHTTPTransport:
    name = "public_http"

    def __init__(self) -> None:
        self._opener = build_opener(_PublicRedirectHandler())

    def fetch(self, request: AcquisitionRequest) -> PageSnapshot:
        validate_public_url(request.url)
        headers = {"User-Agent": _DEFAULT_USER_AGENT, **dict(request.headers)}
        native = Request(request.url, headers=headers, method="GET")
        try:
            with self._opener.open(native, timeout=request.timeout_s) as response:
                status = int(getattr(response, "status", 200))
                final_url = response.geturl()
                validate_public_url(final_url)
                response_headers = {key: value for key, value in response.headers.items()}
                content_type = response.headers.get("Content-Type") or "application/octet-stream"
                body = response.read(request.max_bytes + 1)
        except AcquisitionError:
            raise
        except Exception as exc:
            raise AcquisitionError(f"public HTTP transport failed for {request.url}: {exc}") from exc
        if len(body) > request.max_bytes:
            raise AcquisitionError(
                f"HTTP response exceeds max_bytes={request.max_bytes} for {request.url}"
            )
        if status >= 400:
            raise AcquisitionError(f"HTTP status {status} for {request.url}")
        return PageSnapshot(
            requested_url=request.url,
            final_url=final_url,
            status_code=status,
            content_type=content_type,
            body=body,
            headers=response_headers,
            rendered=False,
        )
