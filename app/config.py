"""Application configuration loaded from environment variables."""

from dataclasses import dataclass
import os
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    credentials_path: Path
    spreadsheet_id: str
    gemini_api_key: str | None
    gemini_model: str | None
    telegram_bot_token: str | None
    timezone: str


def load_settings() -> Settings:
    load_dotenv()
    credentials_value = os.getenv("GOOGLE_CREDENTIALS_PATH")
    spreadsheet_id = os.getenv("GOOGLE_SPREADSHEET_ID")

    if not credentials_value:
        raise RuntimeError("GOOGLE_CREDENTIALS_PATH belum dikonfigurasi.")
    if not spreadsheet_id or spreadsheet_id == "YOUR_SPREADSHEET_ID":
        raise RuntimeError("GOOGLE_SPREADSHEET_ID belum dikonfigurasi.")

    return Settings(
        credentials_path=Path(credentials_value).expanduser(),
        spreadsheet_id=spreadsheet_id,
        gemini_api_key=os.getenv("GEMINI_API_KEY"),
        gemini_model=os.getenv("GEMINI_MODEL"),
        telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN"),
        timezone=os.getenv("TIMEZONE", "Asia/Jakarta"),
    )
