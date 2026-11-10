"""Gemini vision OCR: invoice image/PDF -> structured InvoiceData."""

import json
import logging

from google import genai
from google.genai import types

from .config import get_settings
from .models import InvoiceData

logger = logging.getLogger(__name__)

SUPPORTED_MIME_TYPES = {
    "image/jpeg",
    "image/jpg",
    "image/png",
    "image/webp",
    "image/heic",
    "image/heif",
    "application/pdf",
}

PROMPT = """\
Eres un experto en facturación y comprobantes fiscales de la República Dominicana.
Analiza la imagen o PDF adjunto y extrae únicamente estos campos:

- rnc: RNC o cédula del EMISOR (vendedor). Devuélvelo tal como aparece, con guiones.
- ncf: número de comprobante fiscal (NCF o e-NCF), por ejemplo B0100000123 o E310000000001.
- emisor: razón social o nombre comercial del EMISOR. No uses los datos del cliente.
- fecha: fecha de emisión en formato ISO YYYY-MM-DD. Si aparece DD/MM/YYYY, asígnale
  ese orden (formato dominicano).
- monto_total: monto final pagado, incluyendo ITBIS y cualquier impuesto. Devuelve
  solo el número, sin símbolos de moneda, sin separadores de miles y sin texto.

Reglas:
1. No inventes datos. Si un campo no aparece o no se puede leer con claridad, usa null.
2. Si hay varios totales (subtotal, ITBIS, propina, total), usa el "Total" final.
3. Ignora publicidad, logotipos y textos que no pertenezcan a la factura.
4. Si el documento no es una factura o recibo, devuelve todos los campos en null.
"""

_client: genai.Client | None = None


class InvoiceExtractionError(Exception):
    """Raised when Gemini cannot extract usable invoice data."""


def _get_client() -> genai.Client:
    global _client

    settings = get_settings()
    if not settings.google_api_key:
        raise RuntimeError("GOOGLE_API_KEY no está configurada")

    if _client is None:
        _client = genai.Client(api_key=settings.google_api_key)
    return _client


def normalize_mime_type(mime_type: str | None) -> str:
    mime = (mime_type or "").split(";", 1)[0].strip().lower()
    if mime == "image/jpg":
        return "image/jpeg"
    return mime


def extract_invoice(image_bytes: bytes, mime_type: str) -> InvoiceData:
    """Send the document to Gemini and return validated invoice fields."""
    settings = get_settings()
    mime = normalize_mime_type(mime_type)

    if mime not in SUPPORTED_MIME_TYPES:
        raise InvoiceExtractionError(f"Tipo de archivo no soportado: {mime or 'desconocido'}")
    if not image_bytes:
        raise InvoiceExtractionError("El archivo está vacío")

    client = _get_client()
    logger.info("Enviando documento a Gemini (%s, %s bytes)", mime, len(image_bytes))

    response = client.models.generate_content(
        model=settings.gemini_model,
        contents=[
            PROMPT,
            types.Part.from_bytes(data=image_bytes, mime_type=mime),
        ],
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=InvoiceData,
            temperature=0.1,
        ),
    )

    invoice = _parse_response(response)
    if all(
        getattr(invoice, field) is None
        for field in ("rnc", "ncf", "emisor", "fecha", "monto_total")
    ):
        raise InvoiceExtractionError(
            "No se detectaron datos de factura. Usa una foto más clara o un PDF legible."
        )

    logger.info(
        "Extracción lista: emisor=%r ncf=%r total=%r",
        invoice.emisor,
        invoice.ncf,
        invoice.monto_total,
    )
    return invoice


def _parse_response(response: object) -> InvoiceData:
    parsed = getattr(response, "parsed", None)

    if isinstance(parsed, InvoiceData):
        return parsed
    if isinstance(parsed, dict):
        return InvoiceData(**parsed)

    try:
        text = (getattr(response, "text", None) or "").strip()
    except Exception:
        text = ""

    if not text:
        raise InvoiceExtractionError("Gemini no devolvió contenido")

    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        logger.error("Respuesta no JSON de Gemini: %s", text[:500])
        raise InvoiceExtractionError("Gemini devolvió una respuesta inválida") from exc

    return InvoiceData(**payload)
