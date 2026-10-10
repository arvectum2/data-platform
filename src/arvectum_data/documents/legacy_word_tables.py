"""Pure bounded HTML table projection for legacy Word (.doc) conversion.

No external converter subprocesses or file system access live in this module.
"""

from __future__ import annotations

from html.parser import HTMLParser


class _WvHtmlTableProjector(HTMLParser):
    """Project wvHtml tables into the shared tab-separated row convention.

    Table rows become ``cell1<TAB>cell2...`` lines; prose paragraphs outside
    tables remain newline-separated text.  Script/style content is ignored,
    entities are decoded by the parser, and nested inline markup inside a
    cell contributes its text.  Links, images and converter sidecars are
    never interpreted.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.lines: list[str] = []
        self.table_row_count = 0
        self._table_depth = 0
        self._current_row: list[str] | None = None
        self._current_cell: list[str] | None = None
        self._current_paragraph: list[str] | None = None
        self._ignored_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        normalized = tag.lower()
        if normalized in ("script", "style"):
            self._ignored_depth += 1
        elif normalized == "table":
            self._table_depth += 1
        elif normalized == "tr" and self._table_depth:
            self._current_row = []
        elif normalized in ("td", "th") and self._current_row is not None:
            self._current_cell = []
        elif normalized == "p" and not self._table_depth:
            self._current_paragraph = []
        elif normalized == "br":
            self._flush_paragraph()

    def handle_endtag(self, tag: str) -> None:
        normalized = tag.lower()
        if normalized in ("script", "style"):
            self._ignored_depth = max(0, self._ignored_depth - 1)
        elif normalized in ("td", "th") and self._current_cell is not None:
            self._current_row.append(" ".join("".join(self._current_cell).split()))
            self._current_cell = None
        elif normalized == "tr" and self._current_row is not None:
            cells = [cell for cell in self._current_row if cell]
            if len(cells) >= 2:
                self.lines.append("\t".join(cells))
                self.table_row_count += 1
            elif cells:
                # A single-cell table row carries no column structure; keep
                # its text as ordinary prose instead of dropping it.
                self.lines.append(cells[0])
            self._current_row = None
        elif normalized == "table":
            self._table_depth = max(0, self._table_depth - 1)
        elif normalized == "p":
            self._flush_paragraph()

    def handle_data(self, data: str) -> None:
        if self._ignored_depth:
            return
        if self._current_cell is not None:
            self._current_cell.append(data)
        elif self._current_paragraph is not None:
            self._current_paragraph.append(data)

    def _flush_paragraph(self) -> None:
        if self._current_paragraph is not None:
            text = " ".join("".join(self._current_paragraph).split())
            if text:
                self.lines.append(text)
            self._current_paragraph = None


def _project_wvhtml_tables(html_bytes: bytes, max_chars: int) -> str:
    """Return projected text, or "" when no multi-cell table row survives."""

    try:
        html = html_bytes.decode("utf-8", errors="replace")
    except (LookupError, ValueError):
        return ""
    projector = _WvHtmlTableProjector()
    try:
        projector.feed(html)
    except Exception:  # noqa: BLE001 - any malformed converter HTML fails closed
        return ""
    projector._flush_paragraph()
    if projector.table_row_count < 1:
        return ""
    return "\n".join(projector.lines)[:max_chars]


