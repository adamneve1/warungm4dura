"""Product queries and stock read model for PHASE 1."""

from dataclasses import dataclass
from typing import Any

from .sheets import SheetsGateway


class ProductNotFoundError(Exception):
    """Raised when no active product matches a requested identifier."""


class ProductDataError(Exception):
    """Raised when a product row contains invalid business data."""


@dataclass(frozen=True)
class Product:
    product_id: str
    nama: str
    kategori: str
    satuan: str
    harga_jual: int
    stok: int
    stok_minimum: int
    aktif: bool


class ProductRepository:
    def __init__(self, sheets: SheetsGateway) -> None:
        self._sheets = sheets

    def search(self, query: str) -> list[Product]:
        normalized_query = query.strip().casefold()
        if not normalized_query:
            return []
        return [
            product
            for product in self._active_products()
            if normalized_query in product.nama.casefold()
            or normalized_query in product.product_id.casefold()
            or normalized_query in product.kategori.casefold()
        ]

    def get(self, product_id: str) -> Product:
        product = self.get_any(product_id)
        if not product.aktif:
            raise ProductNotFoundError(f"Product {product_id} tidak ditemukan.")
        return product

    def get_any(self, product_id: str) -> Product:
        normalized_id = product_id.strip().casefold()
        for row in self._sheets.read_rows("Produk"):
            product = self._parse_product(row)
            if product.product_id.casefold() == normalized_id:
                return product
        raise ProductNotFoundError(f"Product {product_id} tidak ditemukan.")

    def stock(self, product_id: str) -> dict[str, Any]:
        product = self.get(product_id)
        status = "OUT_OF_STOCK" if product.stok <= 0 else "LOW" if product.stok <= product.stok_minimum else "OK"
        return {
            "product_id": product.product_id,
            "nama": product.nama,
            "stok": product.stok,
            "stok_minimum": product.stok_minimum,
            "status": status,
        }

    def update_stock(self, product_id: str, new_stock: int) -> None:
        found = self._sheets.find_row("Produk", "Product ID", product_id)
        if found is None:
            raise ProductNotFoundError(f"Product {product_id} tidak ditemukan.")
        row_number, _ = found
        self._sheets.update_cell("Produk", row_number, "Stok", new_stock)

    def list_products(self, include_inactive: bool = False) -> list[Product]:
        products = self._all_products()
        return products if include_inactive else [product for product in products if product.aktif]

    def _active_products(self) -> list[Product]:
        return [product for product in self._all_products() if product.aktif]

    def _all_products(self) -> list[Product]:
        return [self._parse_product(row) for row in self._sheets.read_rows("Produk")]

    @staticmethod
    def _parse_product(row: dict[str, str]) -> Product:
        product_id = row.get("Product ID", "").strip()
        try:
            return Product(
                product_id=product_id,
                nama=row.get("Nama Produk", "").strip(),
                kategori=row.get("Kategori", "").strip(),
                satuan=row.get("Satuan", "").strip(),
                harga_jual=_as_int(row.get("Harga Jual", "")),
                stok=_as_int(row.get("Stok", "")),
                stok_minimum=_as_int(row.get("Stok Minimum", "")),
                aktif=_as_bool(row.get("Aktif", "")),
            )
        except (TypeError, ValueError) as exc:
            raise ProductDataError(f"Data produk {product_id or '<tanpa-id>'} tidak valid.") from exc


def _as_bool(value: str) -> bool:
    normalized = value.strip().casefold()
    if normalized not in {"true", "false"}:
        raise ValueError("Aktif harus TRUE atau FALSE.")
    return normalized == "true"


def _as_int(value: str) -> int:
    normalized = value.strip()
    if not normalized or not normalized.lstrip("-").isdigit() or normalized == "-":
        raise ValueError("Nilai harus berupa integer.")
    return int(normalized)


def product_to_dict(product: Product) -> dict[str, Any]:
    return {
        "product_id": product.product_id,
        "nama": product.nama,
        "kategori": product.kategori,
        "satuan": product.satuan,
        "harga_jual": product.harga_jual,
        "stok": product.stok,
        "aktif": product.aktif,
    }


class ProductService:
    """Business-facing product operations ready for MCP in PHASE 4."""

    def __init__(self, repository: ProductRepository) -> None:
        self._repository = repository

    def search_product(self, query: str) -> list[dict[str, Any]]:
        try:
            return [product_to_dict(product) for product in self._repository.search(query)]
        except ProductDataError:
            return [{"success": False, "error_code": "INVALID_PRODUCT_DATA", "message": "Data product tidak valid."}]

    def get_product(self, product_id: str) -> dict[str, Any]:
        try:
            return {"success": True, "product": product_to_dict(self._repository.get(product_id))}
        except ProductNotFoundError:
            return {
                "success": False,
                "error_code": "PRODUCT_NOT_FOUND",
                "message": f"Product {product_id} tidak ditemukan.",
            }
        except ProductDataError:
            return {"success": False, "error_code": "INVALID_PRODUCT_DATA", "message": f"Data product {product_id} tidak valid."}

    def get_stock(self, product_id: str) -> dict[str, Any]:
        try:
            return {"success": True, **self._repository.stock(product_id)}
        except ProductNotFoundError:
            return {
                "success": False,
                "error_code": "PRODUCT_NOT_FOUND",
                "message": f"Product {product_id} tidak ditemukan.",
            }
        except ProductDataError:
            return {"success": False, "error_code": "INVALID_PRODUCT_DATA", "message": f"Data product {product_id} tidak valid."}
