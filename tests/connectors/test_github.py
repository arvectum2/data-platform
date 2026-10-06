from __future__ import annotations

import json
from urllib.parse import parse_qs, urlsplit

import pytest

from arvectum_data.acquisition import AcquisitionError
from arvectum_data.connectors import DiscoveredResource, GitHubRepositoryConnector


class FakeResponse:
    def __init__(
        self,
        *,
        body: bytes,
        url: str,
        headers: dict[str, str] | None = None,
    ) -> None:
        self._body = body
        self._url = url
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self, size: int = -1) -> bytes:
        if size < 0:
            return self._body
        return self._body[:size]

    def geturl(self) -> str:
        return self._url


class FakeOpener:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self.responses = list(responses)
        self.requests = []

    def open(self, request, timeout):
        self.requests.append((request, timeout))
        response = self.responses.pop(0)
        return response


def _connector(opener: FakeOpener) -> GitHubRepositoryConnector:
    return GitHubRepositoryConnector(opener=opener).with_credentials(
        {"token": "github-secret-token"},
        metadata={"repository": "arvectum2/private-repo", "ref": "main"},
    )


def test_github_private_code_discovery_is_repo_scoped_and_secret_free() -> None:
    payload = {
        "total_count": 2,
        "items": [
            {
                "name": "service.py",
                "path": "src/service.py",
                "sha": "abc123",
                "html_url": "https://github.com/arvectum2/private-repo/blob/main/src/service.py",
                "repository": {"full_name": "arvectum2/private-repo"},
            },
            {
                "name": "ignored.py",
                "path": "src/ignored.py",
                "sha": "bad",
                "html_url": "https://github.com/other/repo/blob/main/src/ignored.py",
                "repository": {"full_name": "other/repo"},
            },
        ],
    }
    url = "https://api.github.com/search/code"
    opener = FakeOpener(
        [
            FakeResponse(
                body=json.dumps(payload).encode(),
                url=url,
                headers={"Content-Type": "application/json"},
            )
        ]
    )
    connector = _connector(opener)

    page = connector.discover("hybrid search", limit=10)

    assert len(page.resources) == 1
    resource = page.resources[0]
    assert resource.provider == "github_repository"
    assert resource.canonical_uri.startswith(
        "https://github.com/arvectum2/private-repo/"
    )
    assert resource.metadata == {
        "repository": "arvectum2/private-repo",
        "path": "src/service.py",
        "sha": "abc123",
        "ref": "main",
    }
    assert "github-secret-token" not in repr(resource)

    request, timeout = opener.requests[0]
    assert timeout == 20.0
    assert request.headers["Authorization"] == "Bearer github-secret-token"
    assert request.headers["X-github-api-version"] == "2026-03-10"
    parsed = urlsplit(request.full_url)
    assert parsed.hostname == "api.github.com"
    query = parse_qs(parsed.query)
    assert query["q"] == ["hybrid search repo:arvectum2/private-repo"]


def test_github_private_fetch_uses_fixed_contents_api_and_raw_media_type() -> None:
    raw = b"def answer():\n    return 42\n"
    opener = FakeOpener(
        [
            FakeResponse(
                body=raw,
                url=(
                    "https://api.github.com/repos/arvectum2/private-repo/"
                    "contents/src/service.py?ref=main"
                ),
                headers={"ETag": '"sha-etag"'},
            )
        ]
    )
    connector = _connector(opener)
    resource = DiscoveredResource(
        canonical_uri=(
            "https://github.com/arvectum2/private-repo/blob/main/src/service.py"
        ),
        provider="github_repository",
        source_type="github_file",
        external_id="abc123",
        title="service.py",
        metadata={
            "repository": "arvectum2/private-repo",
            "path": "src/service.py",
            "sha": "abc123",
            "ref": "main",
        },
    )

    result = connector.fetch(resource)

    assert result.asset.source_url == resource.canonical_uri
    assert result.asset.text == raw.decode()
    assert result.asset.metadata["github"]["repository"] == "arvectum2/private-repo"
    request, _ = opener.requests[0]
    assert request.headers["Accept"] == "application/vnd.github.raw+json"
    assert urlsplit(request.full_url).hostname == "api.github.com"
    assert "github-secret-token" not in repr(result)


def test_github_connector_rejects_unscoped_or_untrusted_inputs() -> None:
    opener = FakeOpener([])
    connector = GitHubRepositoryConnector(opener=opener)

    with pytest.raises(ValueError, match="owner/repo"):
        connector.with_credentials(
            {"token": "secret"},
            metadata={"repository": "https://github.com/arvectum2/repo"},
        )

    with pytest.raises(ValueError, match="unsupported"):
        connector.with_credentials(
            {"token": "secret"},
            metadata={
                "repository": "arvectum2/repo",
                "authorization": "must-not-be-here",
            },
        )

    configured = GitHubRepositoryConnector(
        token="secret",
        repository="arvectum2/repo",
        opener=opener,
    )
    with pytest.raises(AcquisitionError, match="only https://api.github.com"):
        configured._verify_api_url("https://evil.example/token")


def test_github_fetch_rejects_resource_from_other_repository() -> None:
    connector = GitHubRepositoryConnector(
        token="secret",
        repository="arvectum2/repo",
        opener=FakeOpener([]),
    )
    resource = DiscoveredResource(
        canonical_uri="https://github.com/other/repo/blob/main/a.py",
        provider="github_repository",
        metadata={"repository": "other/repo", "path": "a.py"},
    )

    with pytest.raises(ValueError, match="does not match credential scope"):
        connector.fetch(resource)
