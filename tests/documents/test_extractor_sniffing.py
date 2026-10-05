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
