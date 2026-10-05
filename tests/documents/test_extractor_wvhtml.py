"""Structured-first legacy Word extraction through a bounded wvHtml adapter.

Synthetic fixtures only.  Subprocess/file generation is mocked; no host
wvHtml binary is required.
"""

import subprocess
from pathlib import Path

from arvectum_data.documents import extractor


def _doc_bytes() -> bytes:
    return b"\xd0\xcf\x11\xe0legacy-word-binary"


def _install_fake_wvhtml(monkeypatch, html: bytes, *, returncode: int = 0):
    converter = Path("/definitely/not/a/real/wvHtml")
    calls: list = []

    def fake_run(args, **kwargs):
        calls.append(list(args))
        if returncode == 0:
            output_path = Path(args[2])
            output_path.write_bytes(html)
        return subprocess.CompletedProcess(
            args=args, returncode=returncode, stdout=b"", stderr=b""
        )

    monkeypatch.setattr(extractor, "_resolve_wvhtml", lambda: converter)
    monkeypatch.setattr(extractor.subprocess, "run", fake_run)
    return calls


def _write_source(tmp_path: Path) -> Path:
    source = tmp_path / "nmck.doc"
    source.write_bytes(_doc_bytes())
    return source


TABLE_HTML = """<html><body>
<p>Расчет НМЦК на поставку изделий</p>
<table>
<tr><td>№</td><td>Наименование</td><td>Ед.</td><td>Кол-во</td></tr>
<tr><td>1</td><td>Изделие <b>первое</b> &amp; комплект</td><td>шт</td><td>10</td></tr>
<tr><td>2</td><td>Изделие первое</td><td>шт</td><td>5</td></tr>
</table>
<p>Итого по расчету</p>
<script>var x = 1;</script>
<style>p { color: red; }</style>
</body></html>""".encode()


def test_prose_before_and_after_table_preserved(tmp_path, monkeypatch):
    _install_fake_wvhtml(monkeypatch, TABLE_HTML)
    monkeypatch.setattr(extractor, "_MACOS_TEXTUTIL", tmp_path / "missing")

    status, text = extractor.extract_text(str(_write_source(tmp_path)))

    assert status == extractor.EXTRACTED_STATUS
    lines = text.splitlines()
    assert lines[0] == "Расчет НМЦК на поставку изделий"
    assert lines[-1] == "Итого по расчету"


def test_two_row_table_projects_two_tab_rows(tmp_path, monkeypatch):
    _install_fake_wvhtml(monkeypatch, TABLE_HTML)
    monkeypatch.setattr(extractor, "_MACOS_TEXTUTIL", tmp_path / "missing")

    _, text = extractor.extract_text(str(_write_source(tmp_path)))
    tabbed = [line for line in text.splitlines() if "\t" in line]

    assert tabbed == [
        "№\tНаименование\tЕд.\tКол-во",
        "1\tИзделие первое & комплект\tшт\t10",
        "2\tИзделие первое\tшт\t5",
    ]


def test_repeated_row_names_remain_separate(tmp_path, monkeypatch):
    _install_fake_wvhtml(monkeypatch, TABLE_HTML)
    monkeypatch.setattr(extractor, "_MACOS_TEXTUTIL", tmp_path / "missing")

    _, text = extractor.extract_text(str(_write_source(tmp_path)))
    tabbed = [line for line in text.splitlines() if "\t" in line]

    assert len(tabbed) == 3
    assert tabbed[1].split("\t")[0] == "1"
    assert tabbed[2].split("\t")[0] == "2"


def test_script_and_style_ignored(tmp_path, monkeypatch):
    _install_fake_wvhtml(monkeypatch, TABLE_HTML)
    monkeypatch.setattr(extractor, "_MACOS_TEXTUTIL", tmp_path / "missing")

    _, text = extractor.extract_text(str(_write_source(tmp_path)))

    assert "var x" not in text
    assert "color" not in text


def test_nonzero_exit_rejects_partial_html_and_falls_back(tmp_path, monkeypatch):
    monkeypatch.setattr(
        extractor, "_resolve_wvhtml", lambda: Path("/fake/wvHtml")
    )
    fallback = tmp_path / "textutil"
    fallback.write_bytes(b"mock")
    monkeypatch.setattr(extractor, "_MACOS_TEXTUTIL", fallback)

    def fake_run(args, **kwargs):
        if str(args[0]).endswith("wvHtml"):
            return subprocess.CompletedProcess(
                args=args, returncode=139, stdout=b"", stderr=b"segfault"
            )
        return subprocess.CompletedProcess(
            args=args, returncode=0, stdout="плоский текст".encode(), stderr=b""
        )

    monkeypatch.setattr(extractor.subprocess, "run", fake_run)

    status, text = extractor.extract_text(str(_write_source(tmp_path)))

    assert status == extractor.EXTRACTED_STATUS
    assert text == "плоский текст"
    assert "partial" not in text


def test_timeout_falls_back(tmp_path, monkeypatch):
    monkeypatch.setattr(
        extractor, "_resolve_wvhtml", lambda: Path("/fake/wvHtml")
    )

    def fake_run(args, **kwargs):
        if str(args[0]).endswith("wvHtml"):
            raise subprocess.TimeoutExpired(cmd=args, timeout=30)
        return subprocess.CompletedProcess(
            args=args, returncode=0, stdout="резерв".encode(), stderr=b""
        )

    monkeypatch.setattr(extractor.subprocess, "run", fake_run)
    fallback = tmp_path / "textutil"
    fallback.write_bytes(b"mock")
    monkeypatch.setattr(extractor, "_MACOS_TEXTUTIL", fallback)

    status, text = extractor.extract_text(str(_write_source(tmp_path)))

    assert status == extractor.EXTRACTED_STATUS
    assert text == "резерв"


def test_missing_executable_falls_back(tmp_path, monkeypatch):
    monkeypatch.setattr(extractor, "_resolve_wvhtml", lambda: None)
    fallback = tmp_path / "textutil"
    fallback.write_bytes(b"mock")
    monkeypatch.setattr(extractor, "_MACOS_TEXTUTIL", fallback)
    monkeypatch.setattr(
        extractor.subprocess,
        "run",
        lambda args, **kwargs: subprocess.CompletedProcess(
            args=args, returncode=0, stdout="только текст".encode(), stderr=b""
        ),
    )

    status, text = extractor.extract_text(str(_write_source(tmp_path)))

    assert status == extractor.EXTRACTED_STATUS
    assert text == "только текст"


def test_exit_zero_without_table_falls_back(tmp_path, monkeypatch):
    monkeypatch.setattr(
        extractor, "_resolve_wvhtml", lambda: Path("/fake/wvHtml")
    )
    fallback = tmp_path / "textutil"
    fallback.write_bytes(b"mock")
    monkeypatch.setattr(extractor, "_MACOS_TEXTUTIL", fallback)

    def fake_run(args, **kwargs):
        if str(args[0]).endswith("wvHtml"):
            output_path = Path(args[2])
            output_path.write_bytes(
                "<html><body><p>проза без таблиц</p></body></html>".encode()
            )
            return subprocess.CompletedProcess(
                args=args, returncode=0, stdout=b"", stderr=b""
            )
        return subprocess.CompletedProcess(
            args=args, returncode=0, stdout="плоский резерв".encode(), stderr=b""
        )

    monkeypatch.setattr(extractor.subprocess, "run", fake_run)

    status, text = extractor.extract_text(str(_write_source(tmp_path)))

    assert status == extractor.EXTRACTED_STATUS
    assert text == "плоский резерв"


def test_oversized_html_falls_back(tmp_path, monkeypatch):
    monkeypatch.setattr(
        extractor, "_resolve_wvhtml", lambda: Path("/fake/wvHtml")
    )
    monkeypatch.setattr(extractor, "_WVHTML_MAX_HTML_BYTES", 16)

    def fake_run(args, **kwargs):
        if str(args[0]).endswith("wvHtml"):
            Path(args[2]).write_bytes(b"<table>" + b"x" * 64 + b"</table>")
            return subprocess.CompletedProcess(
                args=args, returncode=0, stdout=b"", stderr=b""
            )
        return subprocess.CompletedProcess(
            args=args, returncode=0, stdout="малый резерв".encode(), stderr=b""
        )

    monkeypatch.setattr(extractor.subprocess, "run", fake_run)
    fallback = tmp_path / "textutil"
    fallback.write_bytes(b"mock")
    monkeypatch.setattr(extractor, "_MACOS_TEXTUTIL", fallback)

    status, text = extractor.extract_text(str(_write_source(tmp_path)))

    assert status == extractor.EXTRACTED_STATUS
    assert text == "малый резерв"


def test_temp_directory_and_sidecars_removed(tmp_path, monkeypatch):
    import tempfile

    created: list = []
    real_mkdtemp = tempfile.TemporaryDirectory

    class TrackingDir(real_mkdtemp):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            created.append(self.name)

    monkeypatch.setattr(extractor.tempfile, "TemporaryDirectory", TrackingDir)
    _install_fake_wvhtml(monkeypatch, TABLE_HTML)
    monkeypatch.setattr(extractor, "_MACOS_TEXTUTIL", tmp_path / "missing")
    source = _write_source(tmp_path)
    before = source.read_bytes()

    extractor.extract_text(str(source))

    assert created, "expected a temporary working directory"
    assert all(not Path(name).exists() for name in created)
    assert source.read_bytes() == before


def test_source_file_remains_unchanged(tmp_path, monkeypatch):
    _install_fake_wvhtml(monkeypatch, TABLE_HTML)
    monkeypatch.setattr(extractor, "_MACOS_TEXTUTIL", tmp_path / "missing")
    source = _write_source(tmp_path)
    before = source.read_bytes()

    extractor.extract_text(str(source))

    assert source.read_bytes() == before


def test_subprocess_uses_fixed_executable_no_shell_timeout(tmp_path, monkeypatch):
    calls = _install_fake_wvhtml(monkeypatch, TABLE_HTML)
    monkeypatch.setattr(extractor, "_MACOS_TEXTUTIL", tmp_path / "missing")
    source = _write_source(tmp_path)

    extractor.extract_text(str(source))

    assert len(calls) == 1
    args = calls[0]
    assert args[0] == "/definitely/not/a/real/wvHtml"
    assert args[1].endswith(".doc")
    assert args[2].endswith(".html")


def test_projector_unit_direct():
    projected = extractor._project_wvhtml_tables(TABLE_HTML, 10_000)

    assert "1\tИзделие первое & комплект\tшт\t10" in projected.splitlines()


def test_projector_rejects_tableless_html():
    assert extractor._project_wvhtml_tables(b"<p>no tables</p>", 100) == ""
    assert extractor._project_wvhtml_tables(b"", 100) == ""
