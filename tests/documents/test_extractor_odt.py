"""Bounded ODT procurement source extraction using canonical ODF content.xml."""
from __future__ import annotations

import io
import zipfile

import pytest

from arvectum_data.documents import EXTRACTED_STATUS, extract_text

MIME = "application/vnd.oasis.opendocument.text"
SOURCE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<office:document-content
 xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"
 xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"
 xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0">
 <office:body><office:text>
   <text:h>Обоснование начальной цены</text:h>
   <text:p>Стоимость договора <text:s text:c="2"/> 987000 рублей.</text:p>
   <table:table>
    <table:table-row>
      <table:table-cell><text:p>Услуга</text:p></table:table-cell>
      <table:table-cell><text:p>Цена</text:p></table:table-cell>
    </table:table-row>
    <table:table-row>
      <table:table-cell><text:p>Разработка</text:p></table:table-cell>
      <table:table-cell><text:p>987000</text:p></table:table-cell>
    </table:table-row>
   </table:table>
   <text:p>Оплата <text:tab/> после приемки<text:line-break/>по договору</text:p>
 </office:text></office:body>
</office:document-content>
"""


def odt_blob(xml: str | bytes = SOURCE_XML, *, mime: str = MIME,
             extra: dict[str, bytes] | None = None):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as zip_file:
        zip_file.writestr("mimetype", mime)
        zip_file.writestr("content.xml", xml)
        for key, value in (extra or {}).items():
            zip_file.writestr(key, value)
    return buffer.getvalue()


def test_realistic_odt_title_paragraph_rows_and_odf_whitespace(tmp_path):
    doc = tmp_path / "procurement.odt"
    doc.write_bytes(odt_blob())
    status, text = extract_text(str(doc))
    assert status == EXTRACTED_STATUS
    assert "Обоснование начальной цены" in text
    assert "Стоимость договора    987000 рублей." in text
    assert "Услуга\tЦена" in text
    assert "Разработка\t987000" in text
    assert "Оплата \t после приемки\nпо договору" in text
    assert text.count("987000") == 2


def test_mislabeled_odt_bytes_use_actual_mimetype(tmp_path):
    doc = tmp_path / "procurement.docx"
    doc.write_bytes(odt_blob())
    status, text = extract_text(str(doc))
    assert status == EXTRACTED_STATUS and "Разработка\t987000" in text


@pytest.mark.parametrize("blob", [
    b"not-an-open-document",
    odt_blob(mime="application/zip"),
    odt_blob(xml="<broken"),
    odt_blob(xml="<?xml version='1.0'?><!DOCTYPE a [<!ENTITY xx 'false'>]><a>&xx;</a>"),
    odt_blob(xml="<html><body>not an ODT</body></html>"),
    odt_blob(xml=SOURCE_XML.replace("<office:body>", "").replace("</office:body>", "")),
])
def test_bad_or_malicious_odt_is_not_declared_extracted(tmp_path, blob):
    doc = tmp_path / "procurement.odt"
    doc.write_bytes(blob)
    status, _text = extract_text(str(doc))
    assert status != EXTRACTED_STATUS


def test_zip_bomb_declared_uncompressed_content_exceeds_budget(tmp_path):
    doc = tmp_path / "too-large.odt"
    # compressible XML would inflate more than our strict 8MB member allowance
    large_xml = SOURCE_XML.replace(
        "Обоснование начальной цены", "А" * (9 * 1024 * 1024)
    )
    doc.write_bytes(odt_blob(large_xml))
    status, _text = extract_text(str(doc))
    assert status != EXTRACTED_STATUS


def test_duplicate_content_member_fails_closed(tmp_path):
    doc = tmp_path / "duplicate.odt"
    content = io.BytesIO(odt_blob())
    with zipfile.ZipFile(content, "a") as archive:
        with pytest.warns(UserWarning, match="Duplicate name"):
            archive.writestr("content.xml", SOURCE_XML)
    doc.write_bytes(content.getvalue())
    status, _text = extract_text(str(doc))
    assert status != EXTRACTED_STATUS


def test_odt_max_chars_applies_to_selected_source(tmp_path):
    doc = tmp_path / "nmck.odt"
    doc.write_bytes(odt_blob())
    status, text = extract_text(str(doc), max_chars=37)
    assert status == EXTRACTED_STATUS
    assert len(text) == 37
