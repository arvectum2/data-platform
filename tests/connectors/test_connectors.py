from __future__ import annotations

from dataclasses import dataclass

import pytest

from arvectum_data.acquisition import AcquisitionError, AcquisitionResult
from arvectum_data.connectors import (
    ConnectorExecutor,
    ConnectorPolicy,
    ConnectorRegistry,
    ConnectorState,
    DuckDuckGoHTMLConnector,
    ManualURLConnector,
    SitemapConnector,
    parse_duckduckgo_html,
)
from arvectum_data.engine import RawAsset


@dataclass
class FakeAcquisition:
    payloads: dict[str, tuple[str | None, str | None]]

    def acquire(self, request):
        html, text = self.payloads[request.url]
        return AcquisitionResult(
            asset=RawAsset(
                asset_id="asset",
                source_url=request.url,
                html=html,
                text=text,
            ),
            attempts=(),
        )


def test_registry_reports_connector_capabilities(monkeypatch) -> None:
    monkeypatch.setattr(
        "arvectum_data.connectors.manual.validate_public_url",
        lambda url: None,
    )
    registry = ConnectorRegistry()
    registry.register(ManualURLConnector(acquisition=FakeAcquisition({})))

    assert registry.names() == ("manual_url",)
    health = registry.health()[0]
    assert health.state is ConnectorState.READY
    assert health.capabilities == ("discover", "fetch")

    with pytest.raises(ValueError, match="already registered"):
        registry.register(ManualURLConnector(acquisition=FakeAcquisition({})))


def test_connector_executor_retries_and_rate_limits() -> None:
    now = [0.0]
    sleeps: list[float] = []

    def clock() -> float:
        return now[0]

    def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        now[0] += seconds

    executor = ConnectorExecutor(
        ConnectorPolicy(
            max_attempts=3,
            base_delay_s=0.5,
            max_delay_s=1.0,
            min_interval_s=0.25,
        ),
        sleeper=sleep,
        clock=clock,
    )
    attempts = [0]

    def flaky() -> str:
        attempts[0] += 1
        if attempts[0] < 3:
            raise AcquisitionError("temporary")
        return "ok"

    assert executor.run(flaky) == "ok"
    assert attempts[0] == 3
    assert sleeps[:2] == [0.5, 1.0]

    assert executor.run(lambda: "again") == "again"
    assert sleeps[-1] == 0.25


def test_sitemap_connector_handles_sitemap_index(monkeypatch) -> None:
    monkeypatch.setattr(
        "arvectum_data.connectors.sitemap.validate_public_url",
        lambda url: None,
    )
    root = "https://example.com/sitemap.xml"
    child = "https://example.com/products.xml"
    acquisition = FakeAcquisition(
        {
            root: (
                None,
                f"""<?xml version="1.0"?>
                <sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
                  <sitemap><loc>{child}</loc></sitemap>
                </sitemapindex>""",
            ),
            child: (
                None,
                """<?xml version="1.0"?>
                <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
                  <url><loc>https://example.com/a</loc></url>
                  <url><loc>https://example.com/b</loc></url>
                </urlset>""",
            ),
        }
    )
    connector = SitemapConnector(
        acquisition=acquisition,
        policy=ConnectorPolicy(min_interval_s=0),
    )

    page = connector.discover("https://example.com/", limit=10)

    assert [resource.canonical_uri for resource in page.resources] == [
        "https://example.com/a",
        "https://example.com/b",
    ]
    assert all(resource.provider == "sitemap" for resource in page.resources)


def test_sitemap_connector_falls_back_to_bounded_crawl(monkeypatch) -> None:
    monkeypatch.setattr(
        "arvectum_data.connectors.sitemap.validate_public_url",
        lambda url: None,
    )
    acquisition = FakeAcquisition(
        {
            "https://example.com/sitemap.xml": (None, "not xml"),
            "https://example.com/": (
                '<html><body><a href="/one">One</a><a href="/two">Two</a></body></html>',
                None,
            ),
            "https://example.com/one": ("<html><body>One</body></html>", None),
            "https://example.com/two": ("<html><body>Two</body></html>", None),
        }
    )
    connector = SitemapConnector(
        acquisition=acquisition,
        policy=ConnectorPolicy(max_attempts=1, min_interval_s=0),
    )

    page = connector.discover("https://example.com/", limit=3)

    assert [resource.canonical_uri for resource in page.resources] == [
        "https://example.com/",
        "https://example.com/one",
        "https://example.com/two",
    ]
    assert any(warning.startswith("sitemap_invalid:") for warning in page.warnings)


def test_duckduckgo_parser_is_product_neutral_and_deduplicates() -> None:
    html = """
    <tr><td>
      <a class="result-link" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fa">A</a>
    </td></tr>
    <tr><td class="result-snippet">First result</td></tr>
    <tr><td>
      <a class="result-link" href="https://example.com/a#fragment">A duplicate</a>
    </td></tr>
    <tr><td>
      <a class="result-link" href="https://example.org/b">B</a>
    </td></tr>
    <tr><td class="result-snippet">Second result</td></tr>
    """

    results = parse_duckduckgo_html(html, limit=10)

    assert [item.canonical_uri for item in results] == [
        "https://example.com/a",
        "https://example.org/b",
    ]
    assert results[0].provider == "duckduckgo_html"
    assert results[0].snippet == "First result"


def test_web_connector_builds_generic_search_request() -> None:
    search_url_prefix = "https://lite.duckduckgo.com/lite/?q="
    acquisition = FakeAcquisition(
        {
            f"{search_url_prefix}power+cable": (
                '<a class="result-link" href="https://example.com/a">A</a>',
                None,
            )
        }
    )
    connector = DuckDuckGoHTMLConnector(
        acquisition=acquisition,
        policy=ConnectorPolicy(max_attempts=1, min_interval_s=0),
    )

    page = connector.discover("power cable", limit=5)

    assert [item.canonical_uri for item in page.resources] == ["https://example.com/a"]
