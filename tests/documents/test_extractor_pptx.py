"""Native PPTX text extraction: slide order, tables, safe ZIP and signatures."""

from __future__ import annotations

import zipfile
from pathlib import Path

from arvectum_data.documents.extractor import extract_text


def _slide(label: str, *, table: bool = False) -> bytes:
    rows = (
        '<a:graphic><a:graphicData><a:tbl><a:tr>'
        '<a:tc><a:txBody><a:p><a:r><a:t>Товар</a:t></a:r></a:p></a:txBody></a:tc>'
        '<a:tc><a:txBody><a:p><a:r><a:t>СТАТКОМ</a:t></a:r></a:p></a:txBody></a:tc>'
        '</a:tr></a:tbl></a:graphicData></a:graphic>'
        if table else ""
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"'
        ' xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
        '<p:cSld><p:spTree><p:sp><p:txBody>'
        '<a:p><a:r><a:t>' + label + '</a:t></a:r></a:p>'
        '</p:txBody></p:sp>' + rows + '</p:spTree></p:cSld></p:sld>'
    ).encode()


def _make_pptx(path: Path, *, reordered: bool = False) -> None:
    p = "http://schemas.openxmlformats.org/presentationml/2006/main"
    r = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    pr = "http://schemas.openxmlformats.org/package/2006/relationships"
    relationships = f'''<Relationships xmlns="{pr}">
    <Relationship Id="rId1" Target="slides/slide1.xml"/>
    <Relationship Id="rId2" Target="slides/slide2.xml"/>
    </Relationships>'''
    ids = (
        '<p:sldId id="257" r:id="rId2"/><p:sldId id="256" r:id="rId1"/>'
        if reordered else
        '<p:sldId id="256" r:id="rId1"/><p:sldId id="257" r:id="rId2"/>'
    )
    presentation = (
        f'<p:presentation xmlns:p="{p}" xmlns:r="{r}"><p:sldIdLst>'
        + ids + '</p:sldIdLst></p:presentation>'
    )
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("ppt/presentation.xml", presentation)
        z.writestr("ppt/_rels/presentation.xml.rels", relationships)
        z.writestr("ppt/slides/slide1.xml", _slide("УКРМ, 350 кВАр", table=True))
        z.writestr("ppt/slides/slide2.xml", _slide("Реконструкция ПС 220 кВ"))


def test_pptx_extracts_slides_and_spec_table(tmp_path):
    f = tmp_path / "supplier.pptx"
    _make_pptx(f)
    status, text = extract_text(str(f))
    assert status == "extracted"
    assert "=== Slide 1" in text
    assert "УКРМ, 350 кВАр" in text
    assert "Товар\tСТАТКОМ" in text
    assert text.index("УКРМ") < text.index("Реконструкция")


def test_pptx_respects_presentation_order_not_filename(tmp_path):
    f = tmp_path / "reordered.pptx"
    _make_pptx(f, reordered=True)
    status, text = extract_text(str(f))
    assert status == "extracted"
    assert text.index("Реконструкция") < text.index("УКРМ")


def test_pptx_sniffed_even_if_misnamed(tmp_path):
    f = tmp_path / "supplier.bin"
    _make_pptx(f)
    status, text = extract_text(str(f))
    assert status == "extracted"
    assert "УКРМ" in text


def test_pptx_rejects_dtd_entities(tmp_path):
    f = tmp_path / "bad.pptx"
    with zipfile.ZipFile(f, "w") as z:
        z.writestr("ppt/presentation.xml", "a")
        z.writestr("ppt/slides/slide1.xml", '<!DOCTYPE x [<!ENTITY leak "x">]><x>&leak;</x>')
    status, text = extract_text(str(f))
    assert status == "empty"
    assert not text


def test_pptx_does_not_claim_text_in_image_only_slides(tmp_path):
    f = tmp_path / "image-only.pptx"
    with zipfile.ZipFile(f, "w") as z:
        z.writestr("ppt/presentation.xml", "<document/>")
        z.writestr("ppt/slides/slide1.xml",
                   '<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"/>')
    status, text = extract_text(str(f))
    assert status == "empty" and text == ""


def test_pptx_existing_binary_other_unsupported(tmp_path):
    f = tmp_path / "code.pptx"
    f.write_bytes(b"not-zip-not-slide")
    status, text = extract_text(str(f))
    assert status == "empty" and text == ""
