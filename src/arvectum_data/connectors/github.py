from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any
from urllib.error import HTTPError
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from ..acquisition import AcquisitionAttempt, AcquisitionError, AcquisitionResult
from ..engine.models import RawAsset
from .models import (
    ConnectorHealth,
    ConnectorPolicy,
    ConnectorState,
    DiscoveryPage,
    DiscoveredResource,
)
from .policy import ConnectorExecutor


_API_ORIGIN = "https://api.github.com"
_API_VERSION = "2026-03-10"
_USER_AGENT = "ArvectumDataPlatform/0.6 (+https://arvectum.com)"
_REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


class _RejectRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise AcquisitionError(
            "GitHub credentialed connector refuses redirects while Authorization is present"
        )


class GitHubRepositoryConnector:
    name = "github_repository"

    def __init__(
        self,
        *,
        token: str | None = None,
        repository: str | None = None,
        ref: str | None = None,
        policy: ConnectorPolicy | None = None,
        opener=None,
    ) -> None:
        self.token = token or ""
        self.repository = self._normalize_repository(repository) if repository else None
        self.ref = ref.strip() if ref else None
        if self.ref is not None and len(self.ref) > 256:
            raise ValueError("GitHub ref is too long")
        self.executor = ConnectorExecutor(policy)
        self._opener = opener or build_opener(_RejectRedirects())

    @staticmethod
    def _normalize_repository(value: str | None) -> str:
        cleaned = str(value or "").strip()
        if not _REPOSITORY_RE.fullmatch(cleaned):
            raise ValueError("GitHub repository must use owner/repo syntax")
        return cleaned

    def with_credentials(
        self,
        secrets: Mapping[str, str],
        *,
        metadata: Mapping[str, Any],
    ) -> GitHubRepositoryConnector:
        token = str(secrets.get("token") or "").strip()
        if not token:
            raise ValueError("GitHub credential requires secret field 'token'")
        repository = self._normalize_repository(str(metadata.get("repository") or ""))
        ref = str(metadata.get("ref") or "").strip() or None
        allowed = {"repository", "ref"}
        unknown = set(metadata) - allowed
        if unknown:
            raise ValueError(
                "unsupported GitHub credential metadata: "
                + ", ".join(sorted(str(item) for item in unknown))
            )
        return GitHubRepositoryConnector(
            token=token,
            repository=repository,
            ref=ref,
            policy=self.executor.policy,
            opener=self._opener,
        )

    def _require_configured(self) -> tuple[str, str]:
        if not self.token or not self.repository:
            raise ValueError("GitHub repository connector requires managed credentials")
        return self.token, self.repository

    @staticmethod
    def _api_url(path: str, *, params: Mapping[str, object] | None = None) -> str:
        if not path.startswith("/"):
            raise ValueError("GitHub API path must be absolute")
        url = _API_ORIGIN + path
        if params:
            url += "?" + urlencode(
                {
                    key: value
                    for key, value in params.items()
                    if value is not None
                }
            )
        return url

    @staticmethod
    def _verify_api_url(url: str) -> None:
        parsed = urlsplit(url)
        if (
            parsed.scheme != "https"
            or (parsed.hostname or "").casefold() != "api.github.com"
            or parsed.username is not None
            or parsed.password is not None
            or parsed.port not in {None, 443}
        ):
            raise AcquisitionError("GitHub connector may call only https://api.github.com")

    def _request(
        self,
        url: str,
        *,
        accept: str,
        max_bytes: int,
    ) -> tuple[bytes, Mapping[str, str]]:
        token, _ = self._require_configured()
        self._verify_api_url(url)
        request = Request(
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": accept,
                "X-GitHub-Api-Version": _API_VERSION,
                "User-Agent": _USER_AGENT,
            },
            method="GET",
        )
        try:
            with self._opener.open(request, timeout=20.0) as response:
                final_url = response.geturl()
                self._verify_api_url(final_url)
                body = response.read(max_bytes + 1)
                if len(body) > max_bytes:
                    raise AcquisitionError(
                        f"GitHub response exceeds max_bytes={max_bytes}"
                    )
                return body, {
                    key: value
                    for key, value in response.headers.items()
                }
        except AcquisitionError:
            raise
        except HTTPError as exc:
            raise AcquisitionError(
                f"GitHub API returned HTTP {exc.code}"
            ) from exc
        except Exception as exc:
            raise AcquisitionError(
                f"GitHub API request failed: {type(exc).__name__}"
            ) from exc

    def _request_json(
        self,
        path: str,
        *,
        params: Mapping[str, object] | None = None,
        max_bytes: int = 2_000_000,
    ) -> dict[str, Any]:
        url = self._api_url(path, params=params)
        body, _ = self._request(
            url,
            accept="application/vnd.github+json",
            max_bytes=max_bytes,
        )
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise AcquisitionError("GitHub API returned invalid JSON") from exc
        if not isinstance(payload, dict):
            raise AcquisitionError("GitHub API returned an invalid payload")
        return payload

    def discover(
        self,
        query: str,
        *,
        cursor: str | None = None,
        limit: int = 10,
    ) -> DiscoveryPage:
        _, repository = self._require_configured()
        cleaned = query.strip()
        if not cleaned:
            raise ValueError("GitHub code search query must not be blank")
        if limit < 1 or limit > 100:
            raise ValueError("GitHub code search limit must be between 1 and 100")
        page = 1
        if cursor is not None:
            try:
                page = int(cursor)
            except ValueError as exc:
                raise ValueError("GitHub search cursor must be an integer page") from exc
            if page < 1 or page > 100:
                raise ValueError("GitHub search cursor must be between 1 and 100")

        payload = self.executor.run(
            lambda: self._request_json(
                "/search/code",
                params={
                    "q": f"{cleaned} repo:{repository}",
                    "per_page": limit,
                    "page": page,
                },
            )
        )
        raw_items = payload.get("items")
        if not isinstance(raw_items, list):
            raise AcquisitionError("GitHub code search returned invalid items")

        resources: list[DiscoveredResource] = []
        for index, item in enumerate(raw_items[:limit], start=1):
            if not isinstance(item, dict):
                continue
            item_repository = item.get("repository")
            full_name = (
                str(item_repository.get("full_name") or "")
                if isinstance(item_repository, dict)
                else ""
            )
            path = str(item.get("path") or "").strip()
            html_url = str(item.get("html_url") or "").strip()
            sha = str(item.get("sha") or "").strip() or None
            if full_name != repository or not path or not html_url:
                continue
            html = urlsplit(html_url)
            if html.scheme != "https" or (html.hostname or "").casefold() != "github.com":
                continue
            resources.append(
                DiscoveredResource(
                    canonical_uri=html_url,
                    provider=self.name,
                    source_type="github_file",
                    external_id=sha,
                    title=path.rsplit("/", 1)[-1],
                    rank=index,
                    metadata={
                        "repository": repository,
                        "path": path,
                        "sha": sha,
                        **({"ref": self.ref} if self.ref else {}),
                    },
                )
            )

        total_count = payload.get("total_count")
        try:
            total = min(max(int(total_count), 0), 1000)
        except (TypeError, ValueError):
            total = page * limit
        next_cursor = (
            str(page + 1)
            if resources and page * limit < total
            else None
        )
        return DiscoveryPage(
            resources=tuple(resources),
            next_cursor=next_cursor,
        )

    def fetch(self, resource: DiscoveredResource) -> AcquisitionResult:
        _, repository = self._require_configured()
        if resource.provider != self.name:
            raise ValueError("GitHub connector can fetch only its own resources")
        metadata = dict(resource.metadata)
        if str(metadata.get("repository") or "") != repository:
            raise ValueError("GitHub resource repository does not match credential scope")
        path = str(metadata.get("path") or "").strip()
        if not path:
            raise ValueError("GitHub resource path is missing")
        encoded_path = quote(path, safe="/")
        url = self._api_url(
            f"/repos/{repository}/contents/{encoded_path}",
            params={"ref": self.ref} if self.ref else None,
        )
        body, headers = self.executor.run(
            lambda: self._request(
                url,
                accept="application/vnd.github.raw+json",
                max_bytes=5_000_000,
            )
        )
        text = body.decode("utf-8", errors="replace")
        asset = RawAsset(
            asset_id=(
                f"github-{resource.external_id}"
                if resource.external_id
                else f"github-{repository}-{path}"
            ),
            source_url=resource.canonical_uri,
            text=text,
            metadata={
                "github": {
                    "repository": repository,
                    "path": path,
                    "sha": resource.external_id,
                    "ref": self.ref,
                    "etag": headers.get("ETag") or headers.get("Etag"),
                }
            },
        )
        return AcquisitionResult(
            asset=asset,
            attempts=(
                AcquisitionAttempt(
                    method=self.name,
                    success=True,
                    reason="github_api_success",
                    status_code=200,
                    final_url=url,
                    rendered=False,
                ),
            ),
        )

    def health(self) -> ConnectorHealth:
        return ConnectorHealth(
            name=self.name,
            state=ConnectorState.READY,
            capabilities=("discover", "fetch", "credentials"),
            detail=(
                "credential-aware GitHub repository code connector"
                if self.token and self.repository
                else "credential-aware GitHub repository connector; credential required"
            ),
            metadata={
                "credential_required": True,
                "api_host": "api.github.com",
            },
        )
