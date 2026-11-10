"""Application configuration loaded from environment variables / .env."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Google AI Studio / Gemini
    google_api_key: str = ""
    gemini_model: str = "gemini-3.5-flash-lite"

    # WhatsApp Cloud API
    whatsapp_token: str = ""
    whatsapp_phone_number_id: str = ""
    whatsapp_verify_token: str = "change-me"
    whatsapp_app_secret: str = ""
    whatsapp_api_version: str = "v23.0"

    # Storage
    excel_path: str = "./data/facturas.xlsx"
    excel_sheet_name: str = "Facturas"

    # Optional protection for /process and /report. Empty means disabled.
    app_api_key: str = ""

    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()
