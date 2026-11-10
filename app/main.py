"""FastAPI entrypoint for the Invoice Bot MVP."""

import hashlib
import hmac
import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import (
    BackgroundTasks,
    Depends,
    FastAPI,
    File,
    Header,
    HTTPException,
    Request,
    UploadFile,
)
from fastapi.responses import FileResponse, PlainTextResponse
from starlette.concurrency import run_in_threadpool

from . import whatsapp
from .config import get_settings
from .gemini_ocr import (
    SUPPORTED_MIME_TYPES,
    InvoiceExtractionError,
    extract_invoice,
    normalize_mime_type,
)
from .models import InvoiceData, ProcessResult
from .sheets import append_invoice

settings = get_settings()

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

MAX_UPLOAD_BYTES = 15 * 1024 * 1024


@asynccontextmanager
async def lifespan(_: FastAPI):
    Path(settings.excel_path).parent.mkdir(parents=True, exist_ok=True)
    logger.info("Invoice Bot MVP iniciado | modelo=%s | excel=%s", settings.gemini_model, settings.excel_path)
    yield


app = FastAPI(
    title="Invoice Bot MVP",
    description="WhatsApp invoice photo -> Gemini OCR -> Excel report.",
    version="0.1.0",
    lifespan=lifespan,
)


def _check_api_key(x_api_key: str | None = Header(default=None, alias="X-API-Key")) -> None:
    """Optional protection for manual endpoints. Disabled when APP_API_KEY is empty."""
    if settings.app_api_key and x_api_key != settings.app_api_key:
        raise HTTPException(status_code=401, detail="API key inválida")


def _verify_meta_signature(body: bytes, signature_header: str | None) -> None:
    """Validate X-Hub-Signature-256 when WHATSAPP_APP_SECRET is configured."""
    if not settings.whatsapp_app_secret:
        return

    expected = "sha256=" + hmac.new(
        settings.whatsapp_app_secret.encode("utf-8"),
        body,
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(expected, signature_header or ""):
        raise HTTPException(status_code=403, detail="Firma de webhook inválida")


@app.get("/")
async def root() -> dict[str, str]:
    return {
        "name": "Invoice Bot MVP",
        "docs": "/docs",
        "health": "/health",
        "report": "/report",
    }


@app.get("/health")
async def health() -> dict[str, object]:
    return {
        "status": "ok",
        "model": settings.gemini_model,
        "excel": settings.excel_path,
        "gemini_configured": bool(settings.google_api_key),
        "whatsapp_configured": bool(
            settings.whatsapp_token and settings.whatsapp_phone_number_id
        ),
    }


@app.get("/webhook")
async def verify_webhook(request: Request) -> PlainTextResponse:
    """Meta webhook verification handshake."""
    params = request.query_params

    if (
        params.get("hub.mode") == "subscribe"
        and params.get("hub.verify_token") == settings.whatsapp_verify_token
    ):
        logger.info("Webhook verificado por Meta")
        return PlainTextResponse(params.get("hub.challenge", ""))

    logger.warning("Verificación de webhook rechazada")
    raise HTTPException(status_code=403, detail="Verificación fallida")


@app.post("/webhook")
async def receive_webhook(request: Request, background_tasks: BackgroundTasks) -> dict[str, str]:
    """Receive WhatsApp messages and process them after returning 200 to Meta."""
    body = await request.body()
    _verify_meta_signature(body, request.headers.get("x-hub-signature-256"))

    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="JSON inválido") from exc

    if payload.get("object") != "whatsapp_business_account":
        return {"status": "ignored"}

    queued = 0
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            for message in value.get("messages", []):
                background_tasks.add_task(_process_whatsapp_message, value, message)
                queued += 1

    if queued:
        logger.info("Webhook aceptado: %s mensaje(s) en cola", queued)
        return {"status": "received"}

    return {"status": "ignored"}


async def _process_whatsapp_message(value: dict, message: dict) -> None:
    """Download the media, extract fields, write Excel and reply on WhatsApp."""
    sender = message.get("from", "")
    message_id = message.get("id", "?")
    message_type = message.get("type")

    logger.info("Procesando mensaje %s de %s (tipo=%s)", message_id, sender, message_type)

    if message_type not in {"image", "document"}:
        await whatsapp.send_text(
            sender,
            "Por ahora solo puedo procesar fotos o PDFs de facturas. "
            "Envíame la factura como imagen o documento.",
        )
        return

    media = message.get(message_type) or {}
    media_id = media.get("id")
    if not media_id:
        logger.warning("Mensaje %s sin media_id", message_id)
        await whatsapp.send_text(sender, "No pude obtener el archivo. Intenta enviarlo de nuevo.")
        return

    try:
        media_bytes, mime_type = await whatsapp.download_media(media_id)
        mime_type = normalize_mime_type(mime_type)

        if mime_type not in SUPPORTED_MIME_TYPES:
            await whatsapp.send_text(
                sender,
                f"El formato {mime_type or 'desconocido'} no está soportado. "
                "Envía JPG, PNG, WEBP o PDF.",
            )
            return

        invoice = await run_in_threadpool(extract_invoice, media_bytes, mime_type)
        row = await run_in_threadpool(append_invoice, invoice)

        logger.info("Mensaje %s procesado en la fila %s", message_id, row)
        await whatsapp.send_text(sender, _format_summary(invoice, row))

    except InvoiceExtractionError as exc:
        logger.warning("No se pudo extraer la factura del mensaje %s: %s", message_id, exc)
        await whatsapp.send_text(sender, f"No pude leer la factura: {exc}")
    except Exception:
        logger.exception("Error procesando el mensaje %s", message_id)
        await whatsapp.send_text(
            sender,
            "Ocurrió un error procesando la factura. Intenta de nuevo en unos minutos.",
        )


def _format_summary(invoice: InvoiceData, row: int) -> str:
    total = (
        f"RD$ {invoice.monto_total:,.2f}"
        if invoice.monto_total is not None
        else "—"
    )
    return (
        f"✅ Factura registrada (fila {row})\n\n"
        f"Emisor: {invoice.emisor or '—'}\n"
        f"RNC: {invoice.rnc or '—'}\n"
        f"NCF: {invoice.ncf or '—'}\n"
        f"Fecha: {invoice.fecha or '—'}\n"
        f"Total: {total}"
    )


@app.post("/process", response_model=ProcessResult, dependencies=[Depends(_check_api_key)])
async def process_upload(file: UploadFile = File(...)) -> ProcessResult:
    """Manual test endpoint: upload an invoice image/PDF and get the extracted JSON."""
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="El archivo supera los 15 MB")

    mime_type = normalize_mime_type(file.content_type)
    if mime_type not in SUPPORTED_MIME_TYPES:
        raise HTTPException(
            status_code=415,
            detail=f"Tipo de archivo no soportado: {mime_type or 'desconocido'}",
        )

    try:
        invoice = await run_in_threadpool(extract_invoice, data, mime_type)
    except InvoiceExtractionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Error llamando a Gemini")
        raise HTTPException(
            status_code=502,
            detail="Error al comunicarse con Gemini. Revisa GOOGLE_API_KEY y GEMINI_MODEL.",
        ) from exc

    try:
        row = await run_in_threadpool(append_invoice, invoice)
    except Exception as exc:
        logger.exception("Error escribiendo el archivo Excel")
        raise HTTPException(
            status_code=500,
            detail=(
                "No se pudo escribir el archivo Excel. Verifica que no esté abierto "
                "y que la carpeta de datos sea escribible."
            ),
        ) from exc

    return ProcessResult(invoice=invoice, row=row, file=settings.excel_path)


@app.get("/report", dependencies=[Depends(_check_api_key)])
async def download_report() -> FileResponse:
    """Download the current Excel report."""
    path = Path(settings.excel_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Todavía no hay facturas registradas")

    return FileResponse(
        path,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=path.name,
    )
