from datetime import datetime
from zoneinfo import ZoneInfo

from app.products import ProductRepository
from app.stock import StockService
from app.transactions import InMemoryIdempotencyStore, TransactionIdGenerator, TransactionService


class FakeSheets:
    def __init__(self):
        self.data = {
            "Produk": [
                {"Product ID": "P001", "Nama Produk": "Aqua", "Kategori": "Minuman", "Satuan": "botol", "Harga Jual": "4000", "Stok": "25", "Stok Minimum": "10", "Aktif": "TRUE"},
                {"Product ID": "P002", "Nama Produk": "Indomie", "Kategori": "Makanan", "Satuan": "pcs", "Harga Jual": "3000", "Stok": "10", "Stok Minimum": "2", "Aktif": "TRUE"},
                {"Product ID": "P003", "Nama Produk": "Nonaktif", "Kategori": "Lain", "Satuan": "pcs", "Harga Jual": "100", "Stok": "5", "Stok Minimum": "1", "Aktif": "FALSE"},
            ],
            "Transaksi": [],
            "Detail_Transaksi": [],
            "Stok_Log": [],
        }
        self.fail_on = None

    def read_rows(self, sheet_name):
        return self.data[sheet_name]

    def find_row(self, sheet_name, column_name, value):
        for row_number, row in enumerate(self.data[sheet_name], start=2):
            if row.get(column_name) == value:
                return row_number, row
        return None

    def update_cell(self, sheet_name, row_number, column_name, value):
        if self.fail_on == "update":
            raise RuntimeError("simulated update failure")
        self.data[sheet_name][row_number - 2][column_name] = value

    def append_rows(self, sheet_name, rows):
        if self.fail_on == sheet_name:
            raise RuntimeError("simulated append failure")
        headers = {
            "Transaksi": ["ID Transaksi", "Tanggal", "Waktu", "Total Transaksi", "Metode Bayar", "Catatan"],
            "Detail_Transaksi": ["ID Transaksi", "Product ID", "Nama Produk", "Kategori", "Qty", "Satuan", "Harga Satuan", "Subtotal"],
            "Stok_Log": ["Timestamp", "Product ID", "Nama Produk", "Tipe", "Qty", "Referensi", "Catatan"],
        }[sheet_name]
        self.data[sheet_name].extend(dict(zip(headers, row)) for row in rows)


def setup():
    sheets = FakeSheets()
    products = ProductRepository(sheets)
    clock = lambda: datetime(2026, 9, 8, 7, 30, tzinfo=ZoneInfo("Asia/Jakarta"))
    transactions = TransactionService(products, sheets, TransactionIdGenerator(sheets), InMemoryIdempotencyStore(), clock)
    stock = StockService(products, sheets, clock)
    return sheets, transactions, stock


def test_single_transaction_uses_sheet_price_and_writes_sale_log():
    sheets, service, _ = setup()
    result = service.create_transaction([{"product_id": "P001", "qty": 2, "price": 999999}], "Tunai")
    assert result["success"] is True
    assert result["total"] == 8000
    assert result["transaction_id"] == "TRX-20260908-001"
    assert sheets.data["Produk"][0]["Stok"] == 23
    assert sheets.data["Detail_Transaksi"][0]["Harga Satuan"] == 4000
    assert sheets.data["Stok_Log"][0]["Qty"] == -2


def test_multi_item_total_and_snapshots():
    sheets, service, _ = setup()
    result = service.create_transaction([{"product_id": "P001", "qty": 2}, {"product_id": "P002", "qty": 3}], "QRIS")
    assert result["total"] == 17000
    assert [row["Subtotal"] for row in sheets.data["Detail_Transaksi"]] == [8000, 9000]
    assert [row["Qty"] for row in sheets.data["Stok_Log"]] == [-2, -3]


def test_validation_errors_happen_before_writes():
    sheets, service, _ = setup()
    for items, method, code in [([], "Tunai", "INVALID_TRANSACTION"), ([{"product_id": "P999", "qty": 1}], "Tunai", "PRODUCT_NOT_FOUND"), ([{"product_id": "P003", "qty": 1}], "Tunai", "PRODUCT_INACTIVE"), ([{"product_id": "P001", "qty": 0}], "Tunai", "INVALID_QUANTITY"), ([{"product_id": "P001", "qty": 1}], "Cash", "INVALID_PAYMENT_METHOD")]:
        result = service.create_transaction(items, method)
        assert result["error_code"] == code
    assert sheets.data["Transaksi"] == []
    assert sheets.data["Stok_Log"] == []


def test_insufficient_stock_and_duplicate_items_are_safe():
    sheets, service, _ = setup()
    result = service.create_transaction([{"product_id": "P002", "qty": 6}, {"product_id": "P002", "qty": 5}], "Tunai")
    assert result["error_code"] == "INSUFFICIENT_STOCK"
    assert result["available_stock"] == 10
    assert sheets.data["Transaksi"] == []


def test_idempotency_returns_same_result_and_writes_once():
    sheets, service, _ = setup()
    first = service.create_transaction([{"product_id": "P001", "qty": 1}], "Transfer", idempotency_key="update-1")
    second = service.create_transaction([{"product_id": "P001", "qty": 1}], "Transfer", idempotency_key="update-1")
    assert second == first
    assert len(sheets.data["Transaksi"]) == 1
    assert sheets.data["Produk"][0]["Stok"] == 24


def test_idempotency_conflict_does_not_create_side_effects():
    sheets, service, _ = setup()
    service.create_transaction([{"product_id": "P001", "qty": 1}], "Transfer", idempotency_key="update-1")
    result = service.create_transaction([{"product_id": "P001", "qty": 2}], "Transfer", idempotency_key="update-1")
    assert result["error_code"] == "IDEMPOTENCY_CONFLICT"
    assert len(sheets.data["Transaksi"]) == 1
    assert len(sheets.data["Detail_Transaksi"]) == 1
    assert len(sheets.data["Stok_Log"]) == 1


def test_add_stock_writes_positive_purchase_log():
    sheets, _, stock = setup()
    result = stock.add_stock("P001", 20, "PO-001", "Restock")
    assert result == {"success": True, "product_id": "P001", "qty_added": 20, "stock_before": 25, "stock_after": 45}
    assert sheets.data["Produk"][0]["Stok"] == 45
    assert sheets.data["Stok_Log"][0]["Tipe"] == "PURCHASE"
    assert sheets.data["Stok_Log"][0]["Qty"] == 20


def test_invalid_add_stock_does_not_make_negative_or_write():
    sheets, _, stock = setup()
    result = stock.add_stock("P001", 0)
    assert result["error_code"] == "INVALID_QUANTITY"
    assert sheets.data["Stok_Log"] == []


def test_partial_write_is_not_reported_as_success():
    sheets, service, _ = setup()
    sheets.fail_on = "Detail_Transaksi"
    result = service.create_transaction([{"product_id": "P001", "qty": 1}], "Tunai")
    assert result["success"] is False
    assert result["error_code"] == "TRANSACTION_RECONCILIATION_REQUIRED"


def test_stock_update_failure_is_not_reported_as_success():
    sheets, service, _ = setup()
    sheets.fail_on = "update"
    result = service.create_transaction([{"product_id": "P001", "qty": 1}], "Tunai")
    assert result["success"] is False
    assert result["error_code"] == "TRANSACTION_RECONCILIATION_REQUIRED"


def test_transaction_id_generator_avoids_existing_sequence():
    sheets, _, _ = setup()
    sheets.data["Transaksi"].append({"ID Transaksi": "TRX-20260908-002"})
    assert TransactionIdGenerator(sheets).next(datetime(2026, 9, 8, tzinfo=ZoneInfo("Asia/Jakarta"))) == "TRX-20260908-003"
