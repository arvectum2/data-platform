"""Legacy BIFF spreadsheet row extraction for Russian procurement evidence.

Keep tab-separated source rows in their original order; never coerce absent
cell values into evidence or infer commercial/legal conclusions.
"""

from __future__ import annotations


def _extract_xls(content: bytes) -> str:
    """Extract legacy BIFF .xls workbooks with deterministic row projection."""

    try:
        import xlrd
    except ImportError:
        return ""
    try:
        workbook = xlrd.open_workbook(file_contents=content, on_demand=True)
        lines: list[str] = []
        for sheet in workbook.sheets():
            sheet_lines: list[str] = []
            for row_index in range(sheet.nrows):
                values = [
                    _format_xls_cell(
                        sheet.cell(row_index, column_index),
                        datemode=workbook.datemode,
                        xlrd_module=xlrd,
                    )
                    for column_index in range(sheet.ncols)
                ]
                # Preserve interior empty cells as tab separators but discard
                # trailing empties that carry no table structure.
                while values and not values[-1]:
                    values.pop()
                if values:
                    sheet_lines.append("\t".join(values))
            if sheet_lines:
                lines.append(f"=== {sheet.name} ===")
                lines.extend(sheet_lines)
        workbook.release_resources()
        return "\n".join(lines)
    except Exception:
        return ""


def _format_xls_cell(cell, *, datemode: int, xlrd_module) -> str:
    if cell.ctype in (xlrd_module.XL_CELL_EMPTY, xlrd_module.XL_CELL_BLANK):
        return ""
    if cell.ctype == xlrd_module.XL_CELL_DATE:
        value = xlrd_module.xldate.xldate_as_datetime(cell.value, datemode)
        if value.time().isoformat() == "00:00:00":
            return value.date().isoformat()
        return value.isoformat(sep=" ")
    if cell.ctype == xlrd_module.XL_CELL_BOOLEAN:
        return "TRUE" if bool(cell.value) else "FALSE"
    if cell.ctype == xlrd_module.XL_CELL_NUMBER:
        number = float(cell.value)
        if number.is_integer():
            return str(int(number))
        return format(number, ".15g")
    # Embedded newlines belong to the cell, not to the projected row boundary.
    return " ".join(str(cell.value).split())
