from pathlib import Path
import zipfile

import openpyxl

from arvectum_data.documents import EXTRACTED_STATUS, extract_text, ingest_file
from arvectum_data.processing import ChunkingConfig


def test_ingest_file_is_idempotent_and_preserves_provenance(tmp_path: Path) -> None:
    path = tmp_path / "spec.txt"
    path.write_text(("Условия поставки и оплаты. " * 80).strip(), encoding="utf-8")
    config = ChunkingConfig(chunk_size_chars=180, overlap_chars=30, min_chunk_chars=50)

    first = ingest_file(path, collection_id="test:docs", chunking=config)
    second = ingest_file(path, collection_id="test:docs", chunking=config)

    assert first.resource == second.resource
    assert first.document.document_id == second.document.document_id
    assert first.document.extraction_status == EXTRACTED_STATUS
    assert first.chunks
    assert [chunk.chunk_id for chunk in first.chunks] == [chunk.chunk_id for chunk in second.chunks]
    assert all(chunk.provenance.resource_id == first.resource.resource_id for chunk in first.chunks)
    assert all(chunk.provenance.document_id == first.document.document_id for chunk in first.chunks)


def test_docx_extraction_uses_document_xml(tmp_path: Path) -> None:
    path = tmp_path / "sample.docx"
    xml = """<?xml version="1.0" encoding="UTF-8"?>
    <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
      <w:body><w:p><w:r><w:t>Привет DOCX</w:t></w:r></w:p></w:body>
    </w:document>"""
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("word/document.xml", xml)

    status, text = extract_text(str(path))

    assert status == EXTRACTED_STATUS
    assert "Привет DOCX" in text


def test_xlsx_extraction_preserves_rows(tmp_path: Path) -> None:
    path = tmp_path / "sample.xlsx"
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Data"
    sheet.append(["Товар", "Цена"])
    sheet.append(["Кабель", 125])
    workbook.save(path)
    workbook.close()

    status, text = extract_text(str(path))

    assert status == EXTRACTED_STATUS
    assert "=== Data ===" in text
    assert "Товар\tЦена" in text
    assert "Кабель\t125" in text


def test_pre_chunked_short_text_is_preserved(tmp_path):
    from arvectum_data.documents import ingest_file

    path = tmp_path / "short.txt"
    path.write_text("short text", encoding="utf-8")
    result = ingest_file(
        path,
        collection_id="tests:pre-chunked",
        pre_chunked=True,
    )

    assert len(result.chunks) == 1
    assert result.chunks[0].text == "short text"
    assert result.chunks[0].metadata["pre_chunked"] is True
