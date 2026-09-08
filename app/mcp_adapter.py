"""Business-level MCP adapter over the existing services."""

from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from .products import ProductService
from .reporting import ReportingService
from .stock import StockService
from .transactions import TransactionService

_JAKARTA = ZoneInfo("Asia/Jakarta")


def _resolve_date(date_str: str, clock: "Callable[[], datetime]") -> str:
    """Normalize natural-language or keyword dates to YYYY-MM-DD (Asia/Jakarta).

    Handles: 'today', 'hari ini', 'kemarin', 'yesterday',
             'YYYY-MM-DD', and Excel serial integers.
    Falls through to the original string for all other cases.
    """
    from typing import Callable  # local to avoid circular at module level
    cleaned = date_str.strip().lower()
    now = clock()
    if cleaned in {"today", "hari ini", "sekarang"}:
        return now.strftime("%Y-%m-%d")
    if cleaned in {"yesterday", "kemarin"}:
        return (now - timedelta(days=1)).strftime("%Y-%m-%d")
    return date_str


class MCPToolAdapter:
    """Thin adapter: no Sheets access or business rules live here."""

    def __init__(self, products: ProductService, transactions: TransactionService, stock: StockService, reporting: ReportingService, clock=None) -> None:
        self.products = products
        self.transactions = transactions
        self.stock = stock
        self.reporting = reporting
        self._clock = clock or (lambda: datetime.now(_JAKARTA))

    def search_product(self, query: str) -> list[dict[str, Any]]:
        return self.products.search_product(query)

    def get_product(self, product_id: str) -> dict[str, Any]:
        return self.products.get_product(product_id)

    def get_stock(self, product_id: str) -> dict[str, Any]:
        return self.products.get_stock(product_id)

    def create_transaction(self, items: list[dict[str, Any]], payment_method: str, note: str | None = None, idempotency_key: str | None = None) -> dict[str, Any]:
        return self.transactions.create_transaction(items, payment_method, note, idempotency_key)

    def add_stock(self, product_id: str, qty: int, reference: str | None = None, note: str | None = None) -> dict[str, Any]:
        return self.stock.add_stock(product_id, qty, reference, note)

    def get_daily_sales(self, date: str) -> dict[str, Any]:
        return self.reporting.get_daily_sales(_resolve_date(date, self._clock))

    def get_sales_summary(self, date: str) -> dict[str, Any]:
        return self.reporting.get_sales_summary(_resolve_date(date, self._clock))

    def get_product_sales(self, date: str) -> list[dict[str, Any]] | dict[str, Any]:
        return self.reporting.get_product_sales(_resolve_date(date, self._clock))

    def get_category_sales(self, date: str) -> list[dict[str, Any]] | dict[str, Any]:
        return self.reporting.get_category_sales(_resolve_date(date, self._clock))

    def get_payment_summary(self, date: str) -> list[dict[str, Any]] | dict[str, Any]:
        return self.reporting.get_payment_summary(_resolve_date(date, self._clock))

    def get_stock_status(self, include_inactive: bool = False) -> list[dict[str, Any]] | dict[str, Any]:
        return self.reporting.get_stock_status(include_inactive)

    def get_low_stock(self) -> list[dict[str, Any]] | dict[str, Any]:
        return self.reporting.get_low_stock()

    def get_out_of_stock(self) -> list[dict[str, Any]] | dict[str, Any]:
        return self.reporting.get_out_of_stock()

    def get_stock_movements(self, product_id: str | None = None, start_date: str | None = None, end_date: str | None = None) -> list[dict[str, Any]] | dict[str, Any]:
        return self.reporting.get_stock_movements(product_id, start_date, end_date)

    def tool_functions(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in (
            "search_product", "get_product", "get_stock", "create_transaction", "add_stock",
            "get_daily_sales", "get_sales_summary", "get_product_sales", "get_category_sales",
            "get_payment_summary", "get_stock_status", "get_low_stock", "get_out_of_stock",
            "get_stock_movements",
        )}
