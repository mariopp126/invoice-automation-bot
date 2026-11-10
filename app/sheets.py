"""Append extracted invoices to a local Excel workbook."""

import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from .config import get_settings
from .models import InvoiceData

logger = logging.getLogger(__name__)

HEADERS = ["Fecha", "RNC", "NCF", "Emisor", "Monto Total", "Registrado (UTC)"]
COLUMN_WIDTHS = [14, 18, 20, 40, 16, 22]
AMOUNT_COLUMN = HEADERS.index("Monto Total") + 1

# uvicorn runs with one worker in this MVP, so an in-process lock is enough.
_write_lock = threading.Lock()


def append_invoice(
    invoice: InvoiceData,
    excel_path: str | None = None,
    sheet_name: str | None = None,
) -> int:
    """Append one invoice row and return its Excel row number."""
    settings = get_settings()
    path = Path(excel_path or settings.excel_path)
    sheet = sheet_name or settings.excel_sheet_name

    with _write_lock:
        path.parent.mkdir(parents=True, exist_ok=True)

        if path.exists():
            workbook = load_workbook(path)
            worksheet = (
                workbook[sheet] if sheet in workbook.sheetnames else workbook.create_sheet(sheet)
            )
        else:
            workbook = Workbook()
            worksheet = workbook.active
            worksheet.title = sheet

        if worksheet.max_row == 1 and worksheet["A1"].value is None:
            _write_headers(worksheet)

        worksheet.append(_row_values(invoice))
        row_number = worksheet.max_row

        amount_cell = worksheet.cell(row=row_number, column=AMOUNT_COLUMN)
        amount_cell.number_format = "#,##0.00"
        amount_cell.alignment = Alignment(horizontal="right")

        worksheet.freeze_panes = "A2"
        worksheet.auto_filter.ref = (
            f"A1:{get_column_letter(len(HEADERS))}{max(worksheet.max_row, 1)}"
        )

        _save_atomically(workbook, path)
        logger.info("Factura agregada a %s (fila %s)", path, row_number)
        return row_number


def _row_values(invoice: InvoiceData) -> list[object]:
    return [
        invoice.fecha or "",
        invoice.rnc or "",
        invoice.ncf or "",
        invoice.emisor or "",
        invoice.monto_total if invoice.monto_total is not None else "",
        datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
    ]


def _write_headers(worksheet) -> None:
    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill("solid", fgColor="1F4E78")

    for column, header in enumerate(HEADERS, start=1):
        cell = worksheet.cell(row=1, column=column, value=header)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center", vertical="center")

        worksheet.column_dimensions[get_column_letter(column)].width = COLUMN_WIDTHS[column - 1]

    worksheet.row_dimensions[1].height = 22


def _save_atomically(workbook, path: Path) -> None:
    temp_path = path.with_name(f"{path.name}.tmp")
    try:
        workbook.save(temp_path)
        os.replace(temp_path, path)
    finally:
        if temp_path.exists():
            temp_path.unlink(missing_ok=True)
