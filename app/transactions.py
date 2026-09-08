"""Sales transaction business logic for the Google Sheets MVP."""

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
from typing import Any, Callable, Protocol
from zoneinfo import ZoneInfo

from .products import Product, ProductDataError, ProductNotFoundError, ProductRepository
from .sheets import SheetsGateway


PAYMENT_METHODS = frozenset({"Tunai", "Transfer", "QRIS"})
JAKARTA = ZoneInfo("Asia/Jakarta")


class IdempotencyStore(Protocol):
    def get(self, key: str) -> dict[str, Any] | None: ...

    def get_fingerprint(self, key: str) -> str | None: ...

    def put(self, key: str, result: dict[str, Any], fingerprint: str) -> None: ...


class InMemoryIdempotencyStore:
    def __init__(self) -> None:
        self._results: dict[str, dict[str, Any]] = {}
        self._fingerprints: dict[str, str] = {}

    def get(self, key: str) -> dict[str, Any] | None:
        return self._results.get(key)

    def get_fingerprint(self, key: str) -> str | None:
        return self._fingerprints.get(key)

    def put(self, key: str, result: dict[str, Any], fingerprint: str) -> None:
        self._results[key] = result
        self._fingerprints[key] = fingerprint


class TransactionIdGenerator:
    def __init__(self, sheets: SheetsGateway) -> None:
        self._sheets = sheets

    def next(self, now: datetime) -> str:
        prefix = f"TRX-{now.strftime('%Y%m%d')}-"
        existing = self._sheets.read_rows("Transaksi")
        sequence = 0
        for row in existing:
            transaction_id = row.get("ID Transaksi", "")
            if transaction_id.startswith(prefix):
                try:
                    sequence = max(sequence, int(transaction_id.rsplit("-", 1)[1]))
                except ValueError:
                    continue
        return f"{prefix}{sequence + 1:03d}"


@dataclass(frozen=True)
class PlannedItem:
    product: Product
    qty: int
    subtotal: int


class TransactionService:
    def __init__(
        self,
        products: ProductRepository,
        sheets: SheetsGateway,
        id_generator: TransactionIdGenerator,
        idempotency: IdempotencyStore,
        clock: Callable[[], datetime],
    ) -> None:
        self._products = products
        self._sheets = sheets
        self._id_generator = id_generator
        self._idempotency = idempotency
        self._clock = clock

    def create_transaction(
        self,
        items: list[dict[str, Any]],
        payment_method: str,
        note: str | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        fingerprint = _request_fingerprint(items, payment_method, note)
        if idempotency_key:
            previous = self._idempotency.get(idempotency_key)
            if previous is not None:
                if self._idempotency.get_fingerprint(idempotency_key) != fingerprint:
                    return self._error(
                        "IDEMPOTENCY_CONFLICT",
                        "Idempotency key sudah digunakan untuk transaksi berbeda.",
                    )
                return previous
        if not items:
            return self._error("INVALID_TRANSACTION", "Items transaksi tidak boleh kosong.")
        if payment_method not in PAYMENT_METHODS:
            return self._error("INVALID_PAYMENT_METHOD", "Metode pembayaran tidak valid.")

        planned: list[PlannedItem] = []
        requested_by_product: dict[str, int] = {}
        for item in items:
            product_id = str(item.get("product_id", "")).strip()
            qty = item.get("qty")
            if not isinstance(qty, int) or isinstance(qty, bool) or qty <= 0:
                return self._error("INVALID_QUANTITY", "Qty harus lebih besar dari 0.")
            try:
                product = self._products.get_any(product_id)
            except ProductNotFoundError:
                return self._error(
                    "PRODUCT_NOT_FOUND", f"Product {product_id} tidak ditemukan.", product_id=product_id
                )
            except ProductDataError:
                return self._error("INVALID_PRODUCT_DATA", f"Data product {product_id} tidak valid.", product_id=product_id)
            if not product.aktif:
                return self._error(
                    "PRODUCT_INACTIVE", f"Product {product.product_id} tidak aktif.", product_id=product.product_id
                )
            requested_by_product[product.product_id] = requested_by_product.get(product.product_id, 0) + qty
            planned.append(PlannedItem(product, qty, qty * product.harga_jual))

        for product_id, requested_qty in requested_by_product.items():
            product = next(item.product for item in planned if item.product.product_id == product_id)
            if product.stok < requested_qty:
                return self._error(
                    "INSUFFICIENT_STOCK",
                    "Stok tidak mencukupi.",
                    product_id=product.product_id,
                    available_stock=product.stok,
                    requested_qty=requested_qty,
                )

        now = self._clock().astimezone(JAKARTA)
        transaction_id = self._id_generator.next(now)
        total = sum(item.subtotal for item in planned)
        transaction_row = [[
            transaction_id,
            now.strftime("%Y-%m-%d"),
            now.strftime("%H:%M"),
            total,
            payment_method,
            note or "",
        ]]
        detail_rows = [
            [
                transaction_id,
                item.product.product_id,
                item.product.nama,
                item.product.kategori,
                item.qty,
                item.product.satuan,
                item.product.harga_jual,
                item.subtotal,
            ]
            for item in planned
        ]
        try:
            self._sheets.append_rows("Transaksi", transaction_row)
            self._sheets.append_rows("Detail_Transaksi", detail_rows)
            for product_id, requested_qty in requested_by_product.items():
                product = next(item.product for item in planned if item.product.product_id == product_id)
                self._products.update_stock(product_id, product.stok - requested_qty)
            self._sheets.append_rows(
                "Stok_Log",
                [
                    [
                        now.strftime("%Y-%m-%d %H:%M"),
                        item.product.product_id,
                        item.product.nama,
                        "SALE",
                        -item.qty,
                        transaction_id,
                        "Penjualan",
                    ]
                    for item in planned
                ],
            )
        except Exception:
            return self._error(
                "TRANSACTION_RECONCILIATION_REQUIRED",
                "Transaksi gagal sepenuhnya dan membutuhkan reconciliation manual.",
                transaction_id=transaction_id,
            )

        result = {
            "success": True,
            "transaction_id": transaction_id,
            "total": total,
            "payment_method": payment_method,
            "items": [
                {
                    "product_id": item.product.product_id,
                    "nama": item.product.nama,
                    "qty": item.qty,
                    "harga_satuan": item.product.harga_jual,
                    "subtotal": item.subtotal,
                }
                for item in planned
            ],
        }
        if idempotency_key:
            self._idempotency.put(idempotency_key, result, fingerprint)
        return result

    @staticmethod
    def _error(error_code: str, message: str, **details: Any) -> dict[str, Any]:
        return {"success": False, "error_code": error_code, "message": message, **details}


def _request_fingerprint(items: list[dict[str, Any]], payment_method: str, note: str | None) -> str:
    payload = {
        "items": [{"product_id": item.get("product_id"), "qty": item.get("qty")} for item in items],
        "payment_method": payment_method,
        "note": note or "",
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()
