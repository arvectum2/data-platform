"""Bounded, pure HTML relevance-signal extraction.

No crawling, network IO, or site-specific ranking weights in this module.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from html.parser import HTMLParser

_WS_RE = re.compile(r"\s+")


@dataclass(frozen=True, slots=True)
class _PageSignals:
    title: str = ""
    h1: str = ""
    meta_description: str = ""
    visible_text: str = ""


class _SignalHTMLParser(HTMLParser):
    def __init__(self, *, max_visible_chars: int = 20_000) -> None:
        super().__init__(convert_charrefs=True)
        self.max_visible_chars = max_visible_chars
        self._ignored_depth = 0
        self._title_depth = 0
        self._h1_depth = 0
        self.title_parts: list[str] = []
        self.h1_parts: list[str] = []
        self.meta_description = ""
        self.visible_parts: list[str] = []
        self.visible_chars = 0

    def handle_starttag(self, tag, attrs):
        tag = tag.casefold()
        attrs_map = {str(k).casefold(): str(v or "") for k, v in attrs}
        if tag in {"script", "style", "noscript", "svg"}:
            self._ignored_depth += 1
            return
        if tag == "title":
            self._title_depth += 1
        elif tag == "h1":
            self._h1_depth += 1
        elif tag == "meta" and not self.meta_description:
            name = attrs_map.get("name", "").casefold()
            prop = attrs_map.get("property", "").casefold()
            if name == "description" or prop == "og:description":
                self.meta_description = attrs_map.get("content", "").strip()

    def handle_endtag(self, tag):
        tag = tag.casefold()
        if tag in {"script", "style", "noscript", "svg"}:
            if self._ignored_depth:
                self._ignored_depth -= 1
            return
        if tag == "title" and self._title_depth:
            self._title_depth -= 1
        elif tag == "h1" and self._h1_depth:
            self._h1_depth -= 1

    def handle_data(self, data):
        if self._ignored_depth:
            return
        if self.visible_chars >= self.max_visible_chars and not (
            self._title_depth or self._h1_depth
        ):
            return
        cleaned = _WS_RE.sub(" ", data).strip()
        if not cleaned:
            return
        if self._title_depth:
            self.title_parts.append(cleaned)
        if self._h1_depth:
            self.h1_parts.append(cleaned)
        if self.visible_chars < self.max_visible_chars:
            remaining = self.max_visible_chars - self.visible_chars
            chunk = cleaned[:remaining]
            if chunk:
                self.visible_parts.append(chunk)
                self.visible_chars += len(chunk) + 1

    def signals(self) -> _PageSignals:
        return _PageSignals(
            title=_WS_RE.sub(" ", " ".join(self.title_parts)).strip(),
            h1=_WS_RE.sub(" ", " ".join(self.h1_parts)).strip(),
            meta_description=self.meta_description,
            visible_text=_WS_RE.sub(" ", " ".join(self.visible_parts)).strip(),
        )

