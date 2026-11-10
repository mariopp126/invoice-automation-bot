"""Small helpers for the WhatsApp Cloud API."""

import logging

import httpx

from .config import get_settings

logger = logging.getLogger(__name__)

GRAPH_BASE = "https://graph.facebook.com"


def _require_whatsapp_config() -> None:
    settings = get_settings()
    if not settings.whatsapp_token:
        raise RuntimeError("WHATSAPP_TOKEN no está configurado")
    if not settings.whatsapp_phone_number_id:
        raise RuntimeError("WHATSAPP_PHONE_NUMBER_ID no está configurado")


def _auth_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {get_settings().whatsapp_token}"}


async def download_media(media_id: str) -> tuple[bytes, str]:
    """Download a WhatsApp media item and return (bytes, mime_type)."""
    _require_whatsapp_config()
    settings = get_settings()
    info_url = f"{GRAPH_BASE}/{settings.whatsapp_api_version}/{media_id}"

    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        info_response = await client.get(info_url, headers=_auth_headers())
        info_response.raise_for_status()
        info = info_response.json()

        media_url = info.get("url")
        if not media_url:
            raise RuntimeError("WhatsApp no devolvió la URL del archivo")

        media_response = await client.get(media_url, headers=_auth_headers())
        media_response.raise_for_status()
        media_bytes = media_response.content

    mime_type = info.get("mime_type") or "application/octet-stream"
    logger.info("Archivo de WhatsApp descargado (%s, %s bytes)", mime_type, len(media_bytes))
    return media_bytes, mime_type


async def send_text(to: str, body: str) -> None:
    """Send a plain text WhatsApp message. Failures are logged, not raised."""
    settings = get_settings()
    if not to:
        return
    if not settings.whatsapp_token or not settings.whatsapp_phone_number_id:
        logger.warning("WhatsApp no configurado; se omite la respuesta a %s", to)
        return

    url = (
        f"{GRAPH_BASE}/{settings.whatsapp_api_version}/"
        f"{settings.whatsapp_phone_number_id}/messages"
    )
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to,
        "type": "text",
        "text": {"preview_url": False, "body": body[:4096]},
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(url, headers=_auth_headers(), json=payload)
            response.raise_for_status()
    except Exception:
        logger.exception("No se pudo enviar el mensaje de WhatsApp a %s", to)
