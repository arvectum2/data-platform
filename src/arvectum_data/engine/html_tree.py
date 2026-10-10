"""Internal HTML node tree and incremental parser for semantic extraction.

Pure DOM construction only; commercial/offer relevance decisions remain in
html_records.py. Old private imports are retained as compatibility aliases.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser


_VOID_TAGS = {
    "area",
    "base",
    "br",
    "col",
    "embed",
    "hr",
    "img",
    "input",
    "link",
    "meta",
    "param",
    "source",
    "track",
    "wbr",
}


def _compact(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


@dataclass(slots=True)
class _Node:
    tag: str
    attrs: dict[str, str]
    path: str
    parent: _Node | None = None
    children: list[_Node] = field(default_factory=list)
    text_parts: list[str] = field(default_factory=list)
    child_counts: dict[str, int] = field(default_factory=dict)
    _cached_text: str | None = field(default=None, init=False, repr=False)

    def invalidate_text(self) -> None:
        """Invalidate ancestors after an incremental HTMLParser mutation."""
        current: _Node | None = self
        while current is not None and current._cached_text is not None:
            current._cached_text = None
            current = current.parent

    def text(self) -> str:
        # Scoring and boundary discovery request text for overlapping DOM
        # ancestors many times. Memoize the subtree text after its first read.
        if self._cached_text is not None:
            return self._cached_text
        parts = list(self.text_parts)
        for child in self.children:
            text = child.text()
            if text:
                parts.append(text)
        result = _compact(" ".join(parts))
        self._cached_text = result
        return result

    def walk(self):
        yield self
        for child in self.children:
            yield from child.walk()

    def first(self, tags: set[str]) -> _Node | None:
        for node in self.walk():
            if node.tag in tags:
                return node
        return None


class _TreeParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = _Node("document", {}, "document")
        self._stack = [self.root]

    @property
    def current(self) -> _Node:
        return self._stack[-1]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.casefold()
        parent = self.current
        index = parent.child_counts.get(tag, 0) + 1
        parent.child_counts[tag] = index
        node = _Node(
            tag=tag,
            attrs={str(key).casefold(): str(value or "") for key, value in attrs},
            path=f"{parent.path}/{tag}[{index}]",
            parent=parent,
        )
        parent.children.append(node)
        parent.invalidate_text()
        if tag not in _VOID_TAGS:
            self._stack.append(node)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if self._stack[-1].tag == tag.casefold() and tag.casefold() not in _VOID_TAGS:
            self._stack.pop()

    def handle_endtag(self, tag: str) -> None:
        tag = tag.casefold()
        for index in range(len(self._stack) - 1, 0, -1):
            if self._stack[index].tag == tag:
                del self._stack[index:]
                return

    def handle_data(self, data: str) -> None:
        value = _compact(data)
        if value:
            self.current.text_parts.append(value)
            self.current.invalidate_text()
