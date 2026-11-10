"""Smoke tests for the MVP. Gemini and WhatsApp calls are mocked."""

from unittest.mock import AsyncMock

import pytest
from openpyxl import load_workbook

from app.models import InvoiceData

SAMPLE_INVOICE = InvoiceData(
    rnc="1-31-23456-7",
    ncf="B0100000123",
    emisor="FERRETERÍA EL MARTILLO, SRL",
    fecha="2026-11-05",
    monto_total=4720.0,
)


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_webhook_verification(client):
    response = client.get(
        "/webhook",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": "test-verify-token",
            "hub.challenge": "123456",
        },
    )
    assert response.status_code == 200
    assert response.text == "123456"


def test_webhook_verification_rejects_bad_token(client):
    response = client.get(
        "/webhook",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": "wrong-token",
            "hub.challenge": "123456",
        },
    )
    assert response.status_code == 403


def test_webhook_signature_validation(client, monkeypatch):
    import hashlib
    import hmac
    import json

    from app.main import settings

    monkeypatch.setattr(settings, "whatsapp_app_secret", "test-secret")
    payload = {"object": "whatsapp_business_account", "entry": []}
    body = json.dumps(payload).encode("utf-8")
    signature = "sha256=" + hmac.new(b"test-secret", body, hashlib.sha256).hexdigest()

    missing = client.post("/webhook", content=body, headers={"Content-Type": "application/json"})
    assert missing.status_code == 403

    valid = client.post(
        "/webhook",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-Hub-Signature-256": signature,
        },
    )
    assert valid.status_code == 200
    assert valid.json() == {"status": "ignored"}


def test_process_upload_writes_excel_row(client, monkeypatch, tmp_path):
    monkeypatch.setattr("app.main.extract_invoice", lambda _data, _mime: SAMPLE_INVOICE)

    response = client.post(
        "/process",
        files={"file": ("factura.png", b"fake-image-bytes", "image/png")},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["invoice"]["ncf"] == "B0100000123"
    assert payload["row"] == 2

    worksheet = load_workbook(tmp_path / "facturas.xlsx")["Facturas"]
    assert [cell.value for cell in worksheet[1]] == [
        "Fecha",
        "RNC",
        "NCF",
        "Emisor",
        "Monto Total",
        "Registrado (UTC)",
    ]
    assert worksheet["A2"].value == "2026-11-05"
    assert worksheet["B2"].value == "1-31-23456-7"
    assert worksheet["C2"].value == "B0100000123"
    assert worksheet["D2"].value == "FERRETERÍA EL MARTILLO, SRL"
    assert worksheet["E2"].value == 4720.0


def test_process_rejects_unsupported_file(client):
    response = client.post(
        "/process",
        files={"file": ("notas.txt", b"hello", "text/plain")},
    )
    assert response.status_code == 415


def test_process_api_key_protection(client, monkeypatch):
    from app.main import settings

    monkeypatch.setattr(settings, "app_api_key", "secret")
    response = client.post(
        "/process",
        files={"file": ("factura.png", b"fake-image-bytes", "image/png")},
    )
    assert response.status_code == 401


def test_invoice_model_normalizes_common_formats():
    invoice = InvoiceData(
        rnc=" 1-31-23456-7 ",
        ncf=" b0100000123 ",
        emisor=" FERRETERÍA EL MARTILLO, SRL ",
        fecha="05/11/2026",
        monto_total="RD$ 4,720.00",
    )

    assert invoice.rnc == "1-31-23456-7"
    assert invoice.ncf == "B0100000123"
    assert invoice.emisor == "FERRETERÍA EL MARTILLO, SRL"
    assert invoice.fecha == "2026-11-05"
    assert invoice.monto_total == 4720.0


def test_extract_invoice_builds_gemini_request(monkeypatch):
    from app import gemini_ocr

    class FakeModels:
        def __init__(self):
            self.kwargs = None

        def generate_content(self, **kwargs):
            self.kwargs = kwargs

            class Response:
                parsed = SAMPLE_INVOICE
                text = None

            return Response()

    class FakeClient:
        def __init__(self):
            self.models = FakeModels()

    fake_client = FakeClient()
    monkeypatch.setattr(gemini_ocr, "_client", fake_client)

    result = gemini_ocr.extract_invoice(b"fake-image-bytes", "image/png")

    assert result == SAMPLE_INVOICE
    assert fake_client.models.kwargs["model"]
    assert fake_client.models.kwargs["config"].response_mime_type == "application/json"
    assert fake_client.models.kwargs["config"].response_schema is InvoiceData


def test_extract_invoice_rejects_empty_result(monkeypatch):
    from app import gemini_ocr

    class FakeModels:
        def generate_content(self, **_kwargs):
            class Response:
                parsed = InvoiceData()
                text = None

            return Response()

    class FakeClient:
        def __init__(self):
            self.models = FakeModels()

    monkeypatch.setattr(gemini_ocr, "_client", FakeClient())

    with pytest.raises(gemini_ocr.InvoiceExtractionError):
        gemini_ocr.extract_invoice(b"fake-image-bytes", "image/png")


def test_whatsapp_image_flow(client, monkeypatch, tmp_path):
    from app import whatsapp

    monkeypatch.setattr(
        whatsapp,
        "download_media",
        AsyncMock(return_value=(b"fake-image-bytes", "image/jpeg")),
    )
    send_mock = AsyncMock()
    monkeypatch.setattr(whatsapp, "send_text", send_mock)
    monkeypatch.setattr("app.main.extract_invoice", lambda _data, _mime: SAMPLE_INVOICE)

    payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "123",
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {
                                "display_phone_number": "18095550000",
                                "phone_number_id": "123456",
                            },
                            "messages": [
                                {
                                    "from": "18095551234",
                                    "id": "wamid.test",
                                    "timestamp": "1762363200",
                                    "type": "image",
                                    "image": {
                                        "mime_type": "image/jpeg",
                                        "sha256": "abc",
                                        "id": "media-123",
                                    },
                                }
                            ],
                        },
                    }
                ],
            }
        ],
    }

    response = client.post("/webhook", json=payload)
    assert response.status_code == 200
    assert response.json() == {"status": "received"}

    worksheet = load_workbook(tmp_path / "facturas.xlsx")["Facturas"]
    assert worksheet.max_row == 2
    assert worksheet["C2"].value == "B0100000123"

    send_mock.assert_awaited_once()
    assert "Factura registrada" in send_mock.await_args.args[1]
