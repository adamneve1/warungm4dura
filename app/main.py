"""Composition root for MCP and Telegram runtimes."""

from datetime import datetime
import logging
import sys
from zoneinfo import ZoneInfo

from .config import load_settings
from .gemini import GeminiService
from .mcp_adapter import MCPToolAdapter
from .mcp_server import run_mcp_server
from .products import ProductRepository, ProductService
from .reporting import ReportingService
from .sheets import GoogleSheetsClient
from .stock import StockService
from .telegram_bot import TelegramBot
from .transactions import InMemoryIdempotencyStore, TransactionIdGenerator, TransactionService


def create_sheets_client() -> GoogleSheetsClient:
    settings = load_settings()
    return GoogleSheetsClient(settings.credentials_path, settings.spreadsheet_id)


def create_adapter() -> MCPToolAdapter:
    settings = load_settings()
    sheets = GoogleSheetsClient(settings.credentials_path, settings.spreadsheet_id)
    products = ProductRepository(sheets)
    clock = lambda: datetime.now(ZoneInfo(settings.timezone))
    transaction_service = TransactionService(
        products, sheets, TransactionIdGenerator(sheets), InMemoryIdempotencyStore(), clock
    )
    stock_service = StockService(products, sheets, clock)
    return MCPToolAdapter(
        ProductService(products),
        transaction_service,
        stock_service,
        ReportingService(sheets, products),
    )


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    settings = load_settings()
    adapter = create_adapter()
    if "--mcp" in sys.argv:
        run_mcp_server(adapter)
        return
    if "--telegram" in sys.argv:
        if not settings.gemini_api_key or not settings.gemini_model or not settings.telegram_bot_token:
            raise RuntimeError("GEMINI_API_KEY, GEMINI_MODEL, dan TELEGRAM_BOT_TOKEN wajib dikonfigurasi.")
        TelegramBot(
            settings.telegram_bot_token,
            GeminiService(settings.gemini_api_key, settings.gemini_model, adapter),
            transaction_adapter=adapter,
        ).run()
        return
    raise RuntimeError("Pilih runtime: python -m app.main --mcp atau --telegram.")


if __name__ == "__main__":
    main()