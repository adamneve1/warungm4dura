from app.products import ProductNotFoundError, ProductRepository, ProductService, product_to_dict
from app.sheets import GoogleSheetsClient


class FakeSheets:
    def __init__(self, rows):
        self.rows = rows

    def read_rows(self, sheet_name):
        assert sheet_name == "Produk"
        return self.rows

    def update_cell(self, sheet_name, row_number, column_name, value):
        raise AssertionError("not used in PHASE 1")


def repository():
    return ProductRepository(
        FakeSheets(
            [
                {
                    "Product ID": "P001",
                    "Nama Produk": "Aqua 600ml",
                    "Kategori": "Minuman",
                    "Satuan": "botol",
                    "Harga Jual": "4000",
                    "Harga Modal": "3000",
                    "Stok": "25",
                    "Stok Minimum": "10",
                    "Aktif": "TRUE",
                },
                {
                    "Product ID": "P002",
                    "Nama Produk": "Aqua 1.5L",
                    "Kategori": "Minuman",
                    "Satuan": "botol",
                    "Harga Jual": "7000",
                    "Harga Modal": "5000",
                    "Stok": "0",
                    "Stok Minimum": "5",
                    "Aktif": "TRUE",
                },
                {
                    "Product ID": "P003",
                    "Nama Produk": "Rokok Contoh",
                    "Kategori": "Rokok",
                    "Satuan": "bungkus",
                    "Harga Jual": "25000",
                    "Harga Modal": "22000",
                    "Stok": "4",
                    "Stok Minimum": "2",
                    "Aktif": "FALSE",
                },
            ]
        )
    )


def test_search_product_returns_active_matches_only():
    results = repository().search("aqua")
    assert [product.product_id for product in results] == ["P001", "P002"]
    assert product_to_dict(results[0])["harga_jual"] == 4000


def test_get_product_not_found():
    try:
        repository().get("P999")
    except ProductNotFoundError as error:
        assert str(error) == "Product P999 tidak ditemukan."
    else:
        raise AssertionError("expected ProductNotFoundError")


def test_get_stock_reports_low_and_out_of_stock():
    assert repository().stock("P001")["status"] == "OK"
    assert repository().stock("P002")["status"] == "OUT_OF_STOCK"


def test_service_returns_structured_product_not_found_error():
    result = ProductService(repository()).get_product("P999")
    assert result == {
        "success": False,
        "error_code": "PRODUCT_NOT_FOUND",
        "message": "Product P999 tidak ditemukan.",
    }


def test_search_product_parses_unformatted_numeric_sheet_values():
    product_repository = repository()
    product = product_repository._sheets.rows[0]
    product.update({"Product ID": "P001", "Nama Produk": "Pertalite", "Harga Jual": "12000", "Stok": "50"})
    result = product_repository.search("pertalite")
    assert len(result) == 1
    assert result[0].product_id == "P001"
    assert result[0].harga_jual == 12000


class FakeGoogleValues:
    def __init__(self):
        self.request = None

    def get(self, **kwargs):
        self.request = kwargs
        return self

    def execute(self):
        return {"values": [["Product ID", "Harga Jual"], ["P001", 12000]]}


class FakeGoogleSheetsService:
    def __init__(self):
        self.values_api = FakeGoogleValues()

    def spreadsheets(self):
        return self

    def values(self):
        return self.values_api


def test_read_rows_requests_unformatted_values():
    service = FakeGoogleSheetsService()
    client = object.__new__(GoogleSheetsClient)
    client._service = service
    client._spreadsheet_id = "sheet-id"

    rows = client.read_rows("Produk")

    assert rows == [{"Product ID": "P001", "Harga Jual": "12000"}]
    assert service.values_api.request["valueRenderOption"] == "UNFORMATTED_VALUE"
