"""Shared pytest configuration.

Environment variables are set before importing the app so tests never need a
real Gemini key or WhatsApp token.
"""

import os

os.environ["GOOGLE_API_KEY"] = "test-key"
os.environ["WHATSAPP_VERIFY_TOKEN"] = "test-verify-token"
os.environ["WHATSAPP_APP_SECRET"] = ""
os.environ["APP_API_KEY"] = ""
os.environ["EXCEL_PATH"] = "data/test-facturas.xlsx"

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    from app.main import app, settings

    monkeypatch.setattr(settings, "excel_path", str(tmp_path / "facturas.xlsx"))
    monkeypatch.setattr(settings, "excel_sheet_name", "Facturas")
    monkeypatch.setattr(settings, "whatsapp_verify_token", "test-verify-token")
    monkeypatch.setattr(settings, "whatsapp_app_secret", "")
    monkeypatch.setattr(settings, "app_api_key", "")

    with TestClient(app) as test_client:
        yield test_client
