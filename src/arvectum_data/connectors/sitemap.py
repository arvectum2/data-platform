from __future__ import annotations

import xml.etree.ElementTree as ET
from urllib.parse import urlsplit, urlunsplit

from ..acquisition import AcquisitionEngine, AcquisitionRequest, RenderMode
from ..acquisition.security import validate_public_url
from ..crawl import CrawlPolicy, URLDiscoveryCrawler
from .http import PublicHTTPTransport
from .models import ConnectorHealth, ConnectorPolicy, ConnectorState, DiscoveryPage, DiscoveredResource
from .policy import ConnectorExecutor


def _origin_sitemap(url: str) -> str:
    parsed = urlsplit(url)
    return urlunsplit((parsed.scheme, parsed.netloc, "/sitemap.xml", "", ""))


def _locs(xml_text: str) -> tuple[str, tuple[str, ...]]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return "invalid", ()
    local = root.tag.rsplit("}", 1)[-1].casefold()
    values = []
    for node in root.iter():
        if node.tag.rsplit("}", 1)[-1].casefold() != "loc":
            continue
        value = (node.text or "").strip()
        if value:
            values.append(value)
    return local, tuple(values)


class SitemapConnector:
    name = "sitemap"

    def __init__(
        self,
        *,
        acquisition: AcquisitionEngine | None = None,
        policy: ConnectorPolicy | None = None,
        crawl_policy: CrawlPolicy | None = None,
        max_sitemaps: int = 10,
    ) -> None:
        self.acquisition = acquisition or AcquisitionEngine(
            http=PublicHTTPTransport(),
            renderer=None,
        )
        self.executor = ConnectorExecutor(policy)
        self.crawl_policy = crawl_policy or CrawlPolicy(
            max_depth=1,
            max_pages=20,
            max_discovered_urls=200,
            render_mode=RenderMode.NEVER,
        )
        self.max_sitemaps = max_sitemaps

    def discover(
        self,
        query: str,
        *,
        cursor: str | None = None,
        limit: int = 100,
    ) -> DiscoveryPage:
        if cursor is not None or limit < 1:
            return DiscoveryPage(resources=())
        validate_public_url(query)
        sitemap_url = query if urlsplit(query).path.casefold().endswith(".xml") else _origin_sitemap(query)
        urls, warnings = self._discover_sitemap(sitemap_url, limit)
        if not urls:
            urls, crawl_warnings = self._discover_crawl(query, limit)
            warnings.extend(crawl_warnings)

        resources = tuple(
            DiscoveredResource(
                canonical_uri=url,
                provider=self.name,
                source_type="url",
                rank=index,
                metadata={"discovery": "sitemap_or_site"},
            )
            for index, url in enumerate(urls[:limit], start=1)
        )
        return DiscoveryPage(resources=resources, warnings=tuple(warnings))

    def _discover_sitemap(self, sitemap_url: str, limit: int) -> tuple[list[str], list[str]]:
        queue = [sitemap_url]
        seen_sitemaps = set()
        seen_urls = set()
        urls: list[str] = []
        warnings: list[str] = []
        while queue and len(seen_sitemaps) < self.max_sitemaps and len(urls) < limit:
            current = queue.pop(0)
            if current in seen_sitemaps:
                continue
            seen_sitemaps.add(current)
            try:
                validate_public_url(current)
                result = self.executor.run(
                    lambda current=current: self.acquisition.acquire(
                        AcquisitionRequest(
                            url=current,
                            render_mode=RenderMode.NEVER,
                            max_bytes=5_000_000,
                        )
                    )
                )
            except Exception as exc:
                warnings.append(f"sitemap_fetch_failed:{type(exc).__name__}")
                continue
            text = result.asset.text or result.asset.html or ""
            kind, locs = _locs(text)
            if kind == "sitemapindex":
                for loc in locs:
                    if loc not in seen_sitemaps:
                        queue.append(loc)
                continue
            if kind != "urlset":
                warnings.append(f"sitemap_invalid:{current}")
                continue
            for loc in locs:
                try:
                    validate_public_url(loc)
                except Exception:
                    warnings.append("sitemap_non_public_url_skipped")
                    continue
                if loc not in seen_urls:
                    seen_urls.add(loc)
                    urls.append(loc)
                    if len(urls) >= limit:
                        break
        return urls, warnings

    def _discover_crawl(self, query: str, limit: int) -> tuple[list[str], list[str]]:
        crawler = URLDiscoveryCrawler(
            acquisition=self.acquisition,
            policy=self.crawl_policy,
        )
        try:
            result = crawler.discover((query,))
        except Exception as exc:
            return [], [f"crawl_failed:{type(exc).__name__}"]
        urls = []
        seen = set()
        for url in (*result.seeds, *(link.url for link in result.links)):
            if url in seen:
                continue
            seen.add(url)
            urls.append(url)
            if len(urls) >= limit:
                break
        warnings = [f"crawl_failure:{failure.error_type}" for failure in result.failures]
        warnings.extend(f"crawl_limit:{reason}" for reason in result.limit_reasons)
        return urls, warnings

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
            detail="sitemap-first discovery with bounded site-crawl fallback",
        )
