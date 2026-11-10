"""Pydantic models shared by the API, Gemini extraction and Excel writer."""

import re
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class InvoiceData(BaseModel):
    """Fields extracted from a Dominican Republic invoice or receipt."""

    rnc: Optional[str] = Field(
        default=None,
        description="RNC or cédula of the vendor, as printed (digits and dashes).",
    )
    ncf: Optional[str] = Field(
        default=None,
        description="NCF / e-NCF tax receipt number, e.g. B0100000123 or E310000000001.",
    )
    emisor: Optional[str] = Field(
        default=None,
        description="Legal name of the vendor / issuer, not the customer.",
    )
    fecha: Optional[str] = Field(
        default=None,
        description="Issue date in ISO format YYYY-MM-DD.",
    )
    monto_total: Optional[float] = Field(
        default=None,
        description="Final total paid, including taxes, as a plain number.",
    )

    @field_validator("rnc", "ncf", "emisor", "fecha", mode="before")
    @classmethod
    def strip_blank_text(cls, value: object) -> object:
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return value

    @field_validator("ncf", mode="before")
    @classmethod
    def normalize_ncf(cls, value: object) -> object:
        if isinstance(value, str):
            return value.replace(" ", "").upper() or None
        return value

    @field_validator("fecha", mode="before")
    @classmethod
    def normalize_date(cls, value: object) -> object:
        """Accept common date formats and store ISO YYYY-MM-DD when possible."""
        if not isinstance(value, str):
            return value

        raw = value.strip()
        if not raw:
            return None

        for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d"):
            try:
                return datetime.strptime(raw, fmt).date().isoformat()
            except ValueError:
                continue
        return raw

    @field_validator("monto_total", mode="before")
    @classmethod
    def parse_amount(cls, value: object) -> object:
        """Tolerate values such as 'RD$ 2,950.00' or '2.950,00'."""
        if value is None or isinstance(value, (int, float)):
            return value
        if not isinstance(value, str):
            return value

        raw = value.strip()
        if not raw:
            return None

        cleaned = re.sub(r"[^\d.,-]", "", raw)
        if not cleaned:
            return None

        if "," in cleaned and "." in cleaned:
            if cleaned.rfind(",") > cleaned.rfind("."):
                cleaned = cleaned.replace(".", "").replace(",", ".")
            else:
                cleaned = cleaned.replace(",", "")
        elif "," in cleaned:
            # "2,950" is usually thousands; "2,95" is usually a decimal comma.
            if len(cleaned.rsplit(",", 1)[1]) == 3:
                cleaned = cleaned.replace(",", "")
            else:
                cleaned = cleaned.replace(",", ".")

        try:
            return float(cleaned)
        except ValueError:
            return None


class ProcessResult(BaseModel):
    """Response returned by POST /process."""

    invoice: InvoiceData
    row: int
    file: str
