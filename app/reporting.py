"""Read-only sales, stock, and stock-movement reports."""

from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from .products import ProductDataError, ProductRepository
from .sheets import SheetsGateway


class ReportingService:
    def __init__(self, sheets: SheetsGateway, products: ProductRepository) -> None:
        self._sheets = sheets
        self._products = products

    def get_daily_sales(self, date_value: str) -> dict[str, Any]:
        parsed = _parse_date(date_value)
        if isinstance(parsed, dict):
            return parsed
        try:
            transactions = self._read_transactions()
            details = self._read_details()
        except ReportingDataError as exc:
            return {"success": False, "error_code": exc.error_code, "message": str(exc)}
        matching_ids = {row["id"] for row in transactions if row["date"] == parsed}
        matching_transactions = [row for row in transactions if row["id"] in matching_ids]
        total_items = sum(row["qty"] for row in details if row["transaction_id"] in matching_ids)
        revenue = sum(row["total"] for row in matching_transactions)
        return {
            "date": date_value,
            "transaction_count": len(matching_transactions),
            "total_items": total_items,
            "revenue": revenue,
        }

    def get_sales_summary(self, date_value: str) -> dict[str, Any]:
        daily = self.get_daily_sales(date_value)
        if "error_code" in daily:
            return daily
        count = daily["transaction_count"]
        return {
            **daily,
            "average_transaction_value": daily["revenue"] // count if count else 0,
        }

    def get_product_sales(self, date_value: str) -> list[dict[str, Any]] | dict[str, Any]:
        parsed = _parse_date(date_value)
        if isinstance(parsed, dict):
            return parsed
        try:
            transaction_ids = {row["id"] for row in self._read_transactions() if row["date"] == parsed}
            details = self._read_details()
        except ReportingDataError as exc:
            return {"success": False, "error_code": exc.error_code, "message": str(exc)}
        aggregated: dict[str, dict[str, Any]] = {}
        for row in details:
            if row["transaction_id"] not in transaction_ids:
                continue
            product = aggregated.setdefault(row["product_id"], {"product_id": row["product_id"], "nama": row["nama"], "qty_sold": 0, "revenue": 0})
            product["qty_sold"] += row["qty"]
            product["revenue"] += row["subtotal"]
        return sorted(aggregated.values(), key=lambda item: (-item["qty_sold"], item["product_id"]))

    def get_category_sales(self, date_value: str) -> list[dict[str, Any]] | dict[str, Any]:
        parsed = _parse_date(date_value)
        if isinstance(parsed, dict):
            return parsed
        try:
            transaction_ids = {row["id"] for row in self._read_transactions() if row["date"] == parsed}
            details = self._read_details()
        except ReportingDataError as exc:
            return {"success": False, "error_code": exc.error_code, "message": str(exc)}
        aggregated: dict[str, dict[str, Any]] = {}
        for row in details:
            if row["transaction_id"] not in transaction_ids:
                continue
            category = aggregated.setdefault(row["kategori"], {"kategori": row["kategori"], "qty_sold": 0, "revenue": 0})
            category["qty_sold"] += row["qty"]
            category["revenue"] += row["subtotal"]
        return sorted(aggregated.values(), key=lambda item: (-item["qty_sold"], item["kategori"]))

    def get_payment_summary(self, date_value: str) -> list[dict[str, Any]] | dict[str, Any]:
        parsed = _parse_date(date_value)
        if isinstance(parsed, dict):
            return parsed
        aggregated: dict[str, dict[str, Any]] = {}
        try:
            transactions = self._read_transactions()
        except ReportingDataError as exc:
            return {"success": False, "error_code": exc.error_code, "message": str(exc)}
        for row in transactions:
            if row["date"] != parsed:
                continue
            payment = aggregated.setdefault(row["payment_method"], {"payment_method": row["payment_method"], "transaction_count": 0, "revenue": 0})
            payment["transaction_count"] += 1
            payment["revenue"] += row["total"]
        return sorted(aggregated.values(), key=lambda item: item["payment_method"])

    def get_stock_movements(
        self,
        product_id: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> list[dict[str, Any]] | dict[str, Any]:
        start = _parse_date(start_date) if start_date else None
        end = _parse_date(end_date) if end_date else None
        if isinstance(start, dict):
            return start
        if isinstance(end, dict):
            return end
        if start and end and start > end:
            return {"success": False, "error_code": "INVALID_DATE", "message": "start_date tidak boleh setelah end_date."}
        result = []
        for row in self._sheets.read_rows("Stok_Log"):
            movement = _parse_stock_movement(row)
            if movement.get("success") is False:
                return movement
            timestamp_date = movement["timestamp"][:10]
            if product_id and movement["product_id"] != product_id:
                continue
            if start and timestamp_date < start.isoformat():
                continue
            if end and timestamp_date > end.isoformat():
                continue
            result.append(movement)
        return result

    def get_stock_status(self, include_inactive: bool = False) -> list[dict[str, Any]] | dict[str, Any]:
        try:
            products = self._products.list_products(include_inactive)
            return [_stock_status(product) for product in products]
        except ProductDataError as exc:
            return {"success": False, "error_code": "INVALID_PRODUCT_DATA", "message": str(exc)}

    def get_low_stock(self) -> list[dict[str, Any]] | dict[str, Any]:
        result = self.get_stock_status()
        if isinstance(result, dict):
            return result
        return sorted([row for row in result if row["status"] != "OK"], key=lambda row: (row["stok"], row["product_id"]))

    def get_out_of_stock(self) -> list[dict[str, Any]] | dict[str, Any]:
        result = self.get_stock_status()
        if isinstance(result, dict):
            return result
        return [row for row in result if row["status"] == "OUT_OF_STOCK"]

    def _read_transactions(self) -> list[dict[str, Any]]:
        result = []
        for row in self._sheets.read_rows("Transaksi"):
            try:
                result.append({"id": _required(row, "ID Transaksi"), "date": _date_field(row.get("Tanggal", ""), "Transaksi"), "total": _int_field(row.get("Total Transaksi", ""), "Transaksi"), "payment_method": _required(row, "Metode Bayar")})
            except ValueError as exc:
                raise ReportingDataError(str(exc)) from exc
        return result

    def _read_details(self) -> list[dict[str, Any]]:
        result = []
        for row in self._sheets.read_rows("Detail_Transaksi"):
            try:
                result.append({"transaction_id": _required(row, "ID Transaksi"), "product_id": _required(row, "Product ID"), "nama": _required(row, "Nama Produk"), "kategori": _required(row, "Kategori"), "qty": _int_field(row.get("Qty", ""), "Detail_Transaksi"), "subtotal": _int_field(row.get("Subtotal", ""), "Detail_Transaksi")})
            except ValueError as exc:
                raise ReportingDataError(str(exc)) from exc
        return result


class ReportingDataError(Exception):
    def __init__(self, message: str, error_code: str = "INVALID_TRANSACTION_DATA") -> None:
        super().__init__(message)
        self.error_code = error_code


_EXCEL_EPOCH = date(1899, 12, 30)


def _parse_date(value: str | None) -> date | dict[str, Any]:
    """Parse a date value that may be a YYYY-MM-DD string or an Excel serial integer.

    Google Sheets API with UNFORMATTED_VALUE returns date cells as integer serials.
    Excel epoch: serial 1 = 1900-01-01 (with Lotus 1-2-3 off-by-one, so epoch base = 1899-12-30).
    """
    if value is None:
        return {"success": False, "error_code": "INVALID_DATE", "message": "Tanggal harus berformat YYYY-MM-DD."}
    # Handle Excel/Sheets serial integer (e.g. "46273" or 46273)
    stripped = str(value).strip()
    if stripped.lstrip("-").isdigit():
        serial = int(stripped)
        if serial > 0:
            try:
                from datetime import timedelta
                return _EXCEL_EPOCH + timedelta(days=serial)
            except (OverflowError, ValueError):
                pass
    try:
        return datetime.strptime(stripped, "%Y-%m-%d").date()
    except ValueError:
        return {"success": False, "error_code": "INVALID_DATE", "message": "Tanggal harus berformat YYYY-MM-DD."}


def _required(row: dict[str, str], field: str) -> str:
    value = row.get(field, "").strip()
    if not value:
        raise ValueError(f"{field} tidak boleh kosong.")
    return value


def _int_field(value: str, source: str) -> int:
    if not value.strip() or not value.strip().lstrip("-").isdigit():
        raise ValueError(f"Data numeric pada {source} tidak valid.")
    return int(value)


def _date_field(value: str, source: str) -> date:
    parsed = _parse_date(value)
    if isinstance(parsed, dict):
        raise ValueError(f"Tanggal pada {source} tidak valid.")
    return parsed


def _parse_stock_movement(row: dict[str, str]) -> dict[str, Any]:
    timestamp = row.get("Timestamp", "").strip()
    if not row.get("Product ID", "").strip() or not row.get("Nama Produk", "").strip() or not row.get("Tipe", "").strip():
        return {"success": False, "error_code": "INVALID_STOCK_DATA", "message": "Identitas stock log tidak lengkap."}
    try:
        parsed_datetime = datetime.fromisoformat(timestamp)
        if parsed_datetime.tzinfo is None:
            parsed_datetime = parsed_datetime.replace(tzinfo=ZoneInfo("Asia/Jakarta"))
        parsed = parsed_datetime.isoformat()
    except ValueError:
        try:
            parsed = datetime.strptime(timestamp, "%Y-%m-%d %H:%M").replace(tzinfo=ZoneInfo("Asia/Jakarta")).isoformat()
        except ValueError:
            return {"success": False, "error_code": "INVALID_STOCK_DATA", "message": "Timestamp stock log tidak valid."}
    try:
        qty = _int_field(row.get("Qty", ""), "Stok_Log")
    except ValueError:
        return {"success": False, "error_code": "INVALID_STOCK_DATA", "message": "Qty stock log tidak valid."}
    movement_type = row.get("Tipe", "").strip()
    if movement_type == "SALE" and qty >= 0 or movement_type == "PURCHASE" and qty <= 0:
        return {"success": False, "error_code": "INVALID_STOCK_DATA", "message": "Sign qty stock log tidak valid."}
    return {"timestamp": parsed, "product_id": row.get("Product ID", "").strip(), "nama": row.get("Nama Produk", "").strip(), "type": movement_type, "qty": qty, "reference": row.get("Referensi", ""), "note": row.get("Catatan", "")}


def _stock_status(product: Any) -> dict[str, Any]:
    status = "OUT_OF_STOCK" if product.stok <= 0 else "LOW" if product.stok <= product.stok_minimum else "OK"
    return {"product_id": product.product_id, "nama": product.nama, "stok": product.stok, "stok_minimum": product.stok_minimum, "status": status}