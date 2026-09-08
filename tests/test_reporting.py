from app.reporting import ReportingService
from app.products import ProductRepository
from tests.test_transactions import setup


def reporting_service():
    sheets, _, _ = setup()
    sheets.data["Transaksi"] = [
        {"ID Transaksi": "TRX-20260908-001", "Tanggal": "2026-09-08", "Waktu": "10:00", "Total Transaksi": "17000", "Metode Bayar": "Tunai", "Catatan": ""},
        {"ID Transaksi": "TRX-20260908-002", "Tanggal": "2026-09-08", "Waktu": "11:00", "Total Transaksi": "4000", "Metode Bayar": "QRIS", "Catatan": ""},
        {"ID Transaksi": "TRX-20260907-001", "Tanggal": "2026-09-07", "Waktu": "11:00", "Total Transaksi": "3000", "Metode Bayar": "Tunai", "Catatan": ""},
    ]
    sheets.data["Detail_Transaksi"] = [
        {"ID Transaksi": "TRX-20260908-001", "Product ID": "P001", "Nama Produk": "Aqua historis", "Kategori": "Minuman Lama", "Qty": "2", "Satuan": "botol", "Harga Satuan": "4000", "Subtotal": "8000"},
        {"ID Transaksi": "TRX-20260908-001", "Product ID": "P002", "Nama Produk": "Indomie", "Kategori": "Makanan", "Qty": "3", "Satuan": "pcs", "Harga Satuan": "3000", "Subtotal": "9000"},
        {"ID Transaksi": "TRX-20260908-002", "Product ID": "P001", "Nama Produk": "Aqua historis", "Kategori": "Minuman Lama", "Qty": "1", "Satuan": "botol", "Harga Satuan": "4000", "Subtotal": "4000"},
    ]
    sheets.data["Stok_Log"] = [
        {"Timestamp": "2026-09-08 10:00", "Product ID": "P001", "Nama Produk": "Aqua historis", "Tipe": "SALE", "Qty": "-2", "Referensi": "TRX-20260908-001", "Catatan": "Penjualan"},
        {"Timestamp": "2026-09-08T12:00:00+07:00", "Product ID": "P001", "Nama Produk": "Aqua historis", "Tipe": "PURCHASE", "Qty": "20", "Referensi": "PO-1", "Catatan": "Restock"},
    ]
    return sheets, ReportingService(sheets, ProductRepository(sheets))


def test_daily_sales_summary_and_average_round_down():
    _, service = reporting_service()
    assert service.get_daily_sales("2026-09-08") == {"date": "2026-09-08", "transaction_count": 2, "total_items": 6, "revenue": 21000}
    assert service.get_sales_summary("2026-09-08")["average_transaction_value"] == 10500
    assert service.get_daily_sales("2026-09-06")["transaction_count"] == 0


def test_product_and_category_reports_use_historical_detail_snapshot():
    _, service = reporting_service()
    assert service.get_product_sales("2026-09-08")[0] == {"product_id": "P001", "nama": "Aqua historis", "qty_sold": 3, "revenue": 12000}
    assert {row["kategori"]: row for row in service.get_category_sales("2026-09-08")} == {
        "Minuman Lama": {"kategori": "Minuman Lama", "qty_sold": 3, "revenue": 12000},
        "Makanan": {"kategori": "Makanan", "qty_sold": 3, "revenue": 9000},
    }


def test_payment_and_stock_movement_reports():
    _, service = reporting_service()
    assert service.get_payment_summary("2026-09-08") == [
        {"payment_method": "QRIS", "transaction_count": 1, "revenue": 4000},
        {"payment_method": "Tunai", "transaction_count": 1, "revenue": 17000},
    ]
    movements = service.get_stock_movements(product_id="P001", start_date="2026-09-08", end_date="2026-09-08")
    assert movements[0]["timestamp"] == "2026-09-08T10:00:00+07:00"
    assert movements[0]["qty"] == -2


def test_stock_status_low_out_and_sorting():
    sheets, service = reporting_service()
    sheets.data["Produk"][0]["Stok"] = "0"
    sheets.data["Produk"][1]["Stok"] = "1"
    assert [row["status"] for row in service.get_stock_status()] == ["OUT_OF_STOCK", "LOW"]
    assert service.get_low_stock()[0]["stok"] == 0
    assert service.get_out_of_stock()[0]["product_id"] == "P001"
    sheets.data["Produk"][0]["Stok"] = "-2"
    assert service.get_stock_status()[0]["status"] == "OUT_OF_STOCK"


def test_invalid_date_and_invalid_sheet_data_are_structured():
    sheets, service = reporting_service()
    assert service.get_daily_sales("08-09-2026")["error_code"] == "INVALID_DATE"
    sheets.data["Transaksi"][0]["Total Transaksi"] = "not-number"
    assert service.get_daily_sales("2026-09-08")["error_code"] == "INVALID_TRANSACTION_DATA"
    sheets.data["Transaksi"][0]["Total Transaksi"] = "17000"
    sheets.data["Produk"][0]["Stok"] = "broken"
    assert service.get_stock_status()["error_code"] == "INVALID_PRODUCT_DATA"


def test_invalid_stock_log_sign_is_rejected():
    sheets, service = reporting_service()
    sheets.data["Stok_Log"][0]["Qty"] = "2"
    assert service.get_stock_movements()["error_code"] == "INVALID_STOCK_DATA"