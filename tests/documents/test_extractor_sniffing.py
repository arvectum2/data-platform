from __future__ import annotations

import io
import zipfile

import openpyxl

from arvectum_data.documents import EXTRACTED_STATUS, extract_text


def test_mislabeled_pdf_with_docx_content_is_extracted(tmp_path) -> None:
    source = tmp_path / "electronic-document.pdf"
    document_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
    <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
      <w:body><w:p><w:r><w:t>Customer: cemetery service</w:t></w:r></w:p></w:body>
    </w:document>"""
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("word/document.xml", document_xml)

    status, text = extract_text(str(source))

    assert status == EXTRACTED_STATUS
    assert "cemetery service" in text


def test_misspelled_xslx_with_real_xlsx_content_is_extracted(tmp_path) -> None:
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Calculation"
    sheet.append(["NMCK", 3_400_000])
    payload = io.BytesIO()
    workbook.save(payload)
    workbook.close()

    source = tmp_path / "reportXls.xslx"
    source.write_bytes(payload.getvalue())

    status, text = extract_text(str(source))

    assert status == EXTRACTED_STATUS
    assert "NMCK" in text
    assert "3400000" in text


def test_oversized_ooxml_xml_is_rejected_before_decompression(tmp_path, monkeypatch):
    from arvectum_data.documents import extractor

    payload = tmp_path / "oversized.docx"
    with zipfile.ZipFile(payload, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("word/document.xml", "<xml>" + "а" * 250 + "</xml>")
    monkeypatch.setattr(extractor, "_MAX_OOXML_MEMBER_BYTES", 64)
    assert extract_text(str(payload))[1] == ""


def test_oversized_xlsx_member_is_rejected_before_openpyxl(tmp_path, monkeypatch):
    from arvectum_data.documents import extractor

    payload = tmp_path / "oversized.xlsx"
    workbook = openpyxl.Workbook()
    workbook.active.append(["Документ", "Условия поставки"])
    workbook.save(payload)
    workbook.close()
    monkeypatch.setattr(extractor, "_MAX_OOXML_MEMBER_BYTES", 32)
    assert extract_text(str(payload))[1] == ""
