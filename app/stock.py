"""Stock movements and stock log business logic."""

from datetime import datetime
from typing import Any, Callable

from .products import ProductDataError, ProductNotFoundError, ProductRepository
from .sheets import SheetsGateway


class StockService:
    def __init__(
        self,
        products: ProductRepository,
        sheets: SheetsGateway,
        clock: Callable[[], datetime],
    ) -> None:
        self._products = products
        self._sheets = sheets
        self._clock = clock

    def add_stock(
        self,
        product_id: str,
        qty: int,
        reference: str | None = None,
        note: str | None = None,
    ) -> dict[str, Any]:
        if not isinstance(qty, int) or isinstance(qty, bool) or qty <= 0:
            return {
                "success": False,
                "error_code": "INVALID_QUANTITY",
                "message": "Qty harus lebih besar dari 0.",
            }
        try:
            product = self._products.get_any(product_id)
        except ProductNotFoundError:
            return {
                "success": False,
                "error_code": "PRODUCT_NOT_FOUND",
                "message": f"Product {product_id} tidak ditemukan.",
            }
        except ProductDataError:
            return {
                "success": False,
                "error_code": "INVALID_PRODUCT_DATA",
                "message": f"Data product {product_id} tidak valid.",
            }
        if not product.aktif:
            return {
                "success": False,
                "error_code": "PRODUCT_INACTIVE",
                "message": f"Product {product.product_id} tidak aktif.",
            }

        stock_before = product.stok
        stock_after = stock_before + qty
        try:
            self._products.update_stock(product.product_id, stock_after)
            self._sheets.append_rows(
                "Stok_Log",
                [[
                    self._clock().strftime("%Y-%m-%d %H:%M"),
                    product.product_id,
                    product.nama,
                    "PURCHASE",
                    qty,
                    reference or "",
                    note or "Restock",
                ]],
            )
        except Exception:
            return {
                "success": False,
                "error_code": "STOCK_WRITE_FAILED",
                "message": "Restock gagal diselesaikan dan membutuhkan reconciliation.",
                "product_id": product.product_id,
            }
        return {
            "success": True,
            "product_id": product.product_id,
            "qty_added": qty,
            "stock_before": stock_before,
            "stock_after": stock_after,
        }
