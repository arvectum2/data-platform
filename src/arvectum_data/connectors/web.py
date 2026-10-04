from __future__ import annotations

import re
from html.parser import HTMLParser
from urllib.parse import parse_qs, unquote, urlencode, urlsplit

from ..acquisition import AcquisitionEngine, AcquisitionRequest, RenderMode
from ..acquisition.security import validate_public_url
from ..crawl.links import canonicalize_url
from .http import PublicHTTPTransport
from .models import ConnectorHealth, ConnectorPolicy, ConnectorState, DiscoveryPage, DiscoveredResource
from .policy import ConnectorExecutor


class _DuckDuckGoParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.results: list[dict[str, str]] = []
        self._title = False
        self._snippet = False
        self._current: dict[str, str] = {}

    def handle_starttag(self, tag, attrs):
        values = {str(k): ("" if v is None else str(v)) for k, v in attrs}
        classes = set(values.get("class", "").split())
        if tag == "a" and ({"result__a", "result-link"} & classes):
            self._finish_if_complete()
            self._title = True
            self._current = {"url": _extract_target(values.get("href", ""))}
        elif tag in {"a", "div", "td"} and ({"result__snippet", "result-snippet"} & classes):
            self._snippet = True

    def handle_endtag(self, tag):
        if tag == "a":
            self._title = False
        if tag in {"a", "div", "td"}:
            self._snippet = False

    def handle_data(self, data):
        cleaned = " ".join(data.split())
        if not cleaned:
            return
        if self._title:
            self._current["title"] = (self._current.get("title", "") + " " + cleaned).strip()
        elif self._snippet:
            self._current["snippet"] = (self._current.get("snippet", "") + " " + cleaned).strip()

    def close(self):
        super().close()
        self._finish_if_complete()

    def _finish_if_complete(self):
        if self._current.get("url") and self._current.get("title"):
            self.results.append(dict(self._current))
        self._current = {}
        self._title = False
        self._snippet = False


def _extract_target(href: str) -> str:
    if not href:
        return ""
    parsed = urlsplit(href)
    query = parse_qs(parsed.query)
    if query.get("uddg"):
        return unquote(query["uddg"][0])
    match = re.search(r"(?:^|[?&])uddg=([^&]+)", href)
    if match:
        return unquote(match.group(1))
    return href


def parse_duckduckgo_html(html: str, *, limit: int = 10) -> tuple[DiscoveredResource, ...]:
    parser = _DuckDuckGoParser()
    parser.feed(html)
    parser.close()
    resources = []
    seen = set()
    for item in parser.results:
        normalized = canonicalize_url(item["url"], item["url"])
        if normalized is None or normalized in seen:
            continue
        seen.add(normalized)
        resources.append(
            DiscoveredResource(
                canonical_uri=normalized,
                provider="duckduckgo_html",
                source_type="web_search",
                title=item.get("title") or None,
                snippet=item.get("snippet") or None,
                rank=len(resources) + 1,
            )
        )
        if len(resources) >= limit:
            break
    return tuple(resources)


class DuckDuckGoHTMLConnector:
    name = "duckduckgo_html"
    endpoint = "https://lite.duckduckgo.com/lite/"

    def __init__(
        self,
        *,
        acquisition: AcquisitionEngine | None = None,
        policy: ConnectorPolicy | None = None,
    ) -> None:
        self.acquisition = acquisition or AcquisitionEngine(
            http=PublicHTTPTransport(),
            renderer=None,
        )
        self.executor = ConnectorExecutor(policy or ConnectorPolicy(min_interval_s=0.5))

    def discover(
        self,
        query: str,
        *,
        cursor: str | None = None,
        limit: int = 10,
    ) -> DiscoveryPage:
        cleaned = query.strip()
        if not cleaned:
            raise ValueError("search query must not be blank")
        if cursor is not None:
            return DiscoveryPage(resources=())
        search_url = f"{self.endpoint}?{urlencode({'q': cleaned})}"
        result = self.executor.run(
            lambda: self.acquisition.acquire(
                AcquisitionRequest(
                    url=search_url,
                    render_mode=RenderMode.NEVER,
                    max_bytes=2_000_000,
                )
            )
        )
        html = result.asset.html or result.asset.text or ""
        return DiscoveryPage(
            resources=parse_duckduckgo_html(html, limit=limit),
            warnings=tuple(result.warnings),
        )

    def fetch(self, resource: DiscoveredResource):
        validate_public_url(resource.canonical_uri)
        return self.executor.run(
            lambda: self.acquisition.acquire(
                AcquisitionRequest(
                    url=resource.canonical_uri,
                    render_mode=RenderMode.NEVER,
                )
            )
        )

    def health(self) -> ConnectorHealth:
        return ConnectorHealth(
            name=self.name,
            state=ConnectorState.READY,
            capabilities=("discover", "fetch"),
            detail="generic web discovery via DuckDuckGo HTML",
        )
