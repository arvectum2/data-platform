from __future__ import annotations

from collections import Counter, deque
from concurrent.futures import ThreadPoolExecutor
from collections.abc import Mapping, Sequence
from urllib.parse import urlsplit

from ..acquisition import AcquisitionEngine, AcquisitionRequest
from .links import canonicalize_url, extract_anchors, origin_key
from .models import (
    CrawlDiscoveryResult,
    CrawlFailure,
    CrawlLink,
    CrawlPageRecord,
    CrawlPolicy,
)


class URLDiscoveryCrawler:
    """Bounded deterministic breadth-first URL discovery over generic HTML links."""

    def __init__(
        self,
        *,
        acquisition: AcquisitionEngine | None = None,
        policy: CrawlPolicy | None = None,
    ) -> None:
        self.acquisition = acquisition or AcquisitionEngine()
        self.policy = policy or CrawlPolicy()

    def discover(
        self,
        seeds: Sequence[str],
        *,
        headers: Mapping[str, str] | None = None,
    ) -> CrawlDiscoveryResult:
        if not seeds:
            raise ValueError("at least one seed URL is required")

        canonical_seeds: list[str] = []
        seed_seen: set[str] = set()
        for raw in seeds:
            canonical = canonicalize_url(raw, raw)
            if canonical is None:
                raise ValueError(f"invalid seed URL: {raw!r}")
            if canonical not in seed_seen:
                canonical_seeds.append(canonical)
                seed_seen.add(canonical)
        if not canonical_seeds:
            raise ValueError("at least one valid seed URL is required")

        seed_origins = {origin_key(url) for url in canonical_seeds}
        queue = deque((url, 0) for url in canonical_seeds)
        queued = set(canonical_seeds)
        visited: set[str] = set()
        resolved_pages: set[str] = set()
        known = set(canonical_seeds)

        discovered: list[CrawlLink] = []
        pages: list[CrawlPageRecord] = []
        failures: list[CrawlFailure] = []
        limit_reasons: list[str] = []
        request_headers = {} if headers is None else dict(headers)

        executor = (
            ThreadPoolExecutor(max_workers=self.policy.max_workers)
            if self.policy.max_workers > 1
            else None
        )
        try:
            while queue:
                if len(visited) >= self.policy.max_pages:
                    self._add_limit(limit_reasons, "max_pages")
                    break

                batch = self._next_batch(
                    queue,
                    queued,
                    visited=visited,
                    resolved_pages=resolved_pages,
                    remaining_pages=self.policy.max_pages - len(visited),
                )
                if not batch:
                    break
                for url, _depth in batch:
                    visited.add(url)

                if executor is None:
                    acquired_batch = [
                        self._acquire(url, request_headers)
                        for url, _depth in batch
                    ]
                else:
                    acquired_batch = list(
                        executor.map(
                            lambda item: self._acquire(item[0], request_headers),
                            batch,
                        )
                    )

                # Process acquisition results in deterministic queue order rather than
                # completion order so bounded concurrency cannot change discovery rank.
                for (url, depth), acquired_or_error in zip(
                    batch,
                    acquired_batch,
                    strict=True,
                ):
                    if isinstance(acquired_or_error, Exception):
                        failures.append(
                            CrawlFailure.from_exception(
                                url,
                                depth,
                                acquired_or_error,
                            )
                        )
                        continue
                    acquired = acquired_or_error

                    final_url = canonicalize_url(
                        url,
                        acquired.asset.source_url or url,
                    ) or url
                    resolved_pages.add(final_url)
                    known.add(final_url)
                    scope_allowed = self._scope_allowed(final_url, seed_origins)
                    page_links = 0

                    if (
                        scope_allowed
                        and acquired.asset.html is not None
                        and depth < self.policy.max_depth
                    ):
                        base_href, anchors = extract_anchors(
                            acquired.asset.html,
                            max_links=self.policy.max_links_per_page,
                        )
                        base_url = final_url
                        if base_href:
                            candidate_base = canonicalize_url(final_url, base_href)
                            if candidate_base is not None:
                                base_url = candidate_base

                        for anchor in anchors:
                            if (
                                self.policy.respect_nofollow
                                and "nofollow" in anchor.rel
                            ):
                                continue
                            candidate = canonicalize_url(base_url, anchor.href)
                            if candidate is None:
                                continue
                            if not self._scope_allowed(candidate, seed_origins):
                                continue
                            if self._blocked_by_suffix(candidate):
                                continue
                            if candidate in known:
                                continue
                            if (
                                len(discovered)
                                >= self.policy.max_discovered_urls
                            ):
                                self._add_limit(
                                    limit_reasons,
                                    "max_discovered_urls",
                                )
                                break

                            link = CrawlLink(
                                url=candidate,
                                parent_url=final_url,
                                depth=depth + 1,
                                anchor_text=anchor.text,
                                rel=anchor.rel,
                            )
                            discovered.append(link)
                            known.add(candidate)
                            page_links += 1

                            if (
                                depth + 1 <= self.policy.max_depth
                                and candidate not in visited
                                and candidate not in resolved_pages
                                and candidate not in queued
                            ):
                                queue.append((candidate, depth + 1))
                                queued.add(candidate)

                    pages.append(
                        CrawlPageRecord(
                            url=url,
                            final_url=final_url,
                            depth=depth,
                            rendered=acquired.used_renderer,
                            discovered_links=page_links,
                            scope_allowed=scope_allowed,
                        )
                    )
                    if "max_discovered_urls" in limit_reasons:
                        break

                if "max_discovered_urls" in limit_reasons:
                    break
        finally:
            if executor is not None:
                executor.shutdown(wait=True)

        if queue and len(visited) >= self.policy.max_pages:
            self._add_limit(limit_reasons, "max_pages")

        return CrawlDiscoveryResult(
            seeds=tuple(canonical_seeds),
            links=tuple(discovered),
            pages=tuple(pages),
            failures=tuple(failures),
            limit_reasons=tuple(limit_reasons),
        )

    def _acquire(
        self,
        url: str,
        headers: Mapping[str, str],
    ):
        try:
            return self.acquisition.acquire(
                AcquisitionRequest(
                    url=url,
                    headers=headers,
                    timeout_s=self.policy.timeout_s,
                    max_bytes=self.policy.max_bytes,
                    render_mode=self.policy.render_mode,
                )
            )
        except Exception as exc:
            return exc

    def _next_batch(
        self,
        queue: deque[tuple[str, int]],
        queued: set[str],
        *,
        visited: set[str],
        resolved_pages: set[str],
        remaining_pages: int,
    ) -> list[tuple[str, int]]:
        if remaining_pages <= 0 or not queue:
            return []

        target_depth = queue[0][1]
        selected: list[tuple[str, int]] = []
        deferred: list[tuple[str, int]] = []
        host_counts: Counter[str] = Counter()

        while queue and len(selected) < min(
            self.policy.max_workers,
            remaining_pages,
        ):
            url, depth = queue.popleft()
            queued.discard(url)
            if depth != target_depth:
                queue.appendleft((url, depth))
                queued.add(url)
                break
            if url in visited or url in resolved_pages:
                continue

            host = (urlsplit(url).hostname or "").casefold().rstrip(".")
            if host_counts[host] >= self.policy.max_in_flight_per_host:
                deferred.append((url, depth))
                continue
            host_counts[host] += 1
            selected.append((url, depth))

        for item in reversed(deferred):
            queue.appendleft(item)
            queued.add(item[0])

        return selected

    def _scope_allowed(
        self,
        url: str,
        seed_origins: set[tuple[str, str, int | None]],
    ) -> bool:
        parsed = urlsplit(url)
        host = (parsed.hostname or "").casefold().rstrip(".")
        if origin_key(url) in seed_origins:
            return True
        if self.policy.same_origin:
            return False
        return host in self.policy.allowed_hosts

    def _blocked_by_suffix(self, url: str) -> bool:
        path = urlsplit(url).path.casefold()
        return any(path.endswith(suffix) for suffix in self.policy.blocked_suffixes)

    @staticmethod
    def _add_limit(reasons: list[str], reason: str) -> None:
        if reason not in reasons:
            reasons.append(reason)
