# Warung Madura AI Agent

Backend Python untuk agent kasir Warung Madura dengan Google Sheets sebagai datastore MVP. Implementasi saat ini mencakup **PHASE 1 sampai PHASE 4**: konfigurasi, koneksi Sheets, operasi bisnis, reporting, MCP adapter/server, Gemini orchestration boundary, dan Telegram text bot.

## Arsitektur fase ini

```text
ProductService -> ProductRepository -> SheetsGateway -> Google Sheets
```

`ProductRepository` membaca dan mengubah data berdasarkan nama header, bukan koordinat sel. `ProductService`, `TransactionService`, `StockService`, dan `ReportingService` tetap menjadi sumber kebenaran; MCP, Gemini, dan Telegram hanya adapter/orchestration boundaries.

## Google Cloud setup

1. Pastikan Google Sheets API aktif di Google Cloud Project.
2. Buat atau gunakan service account terpisah, misalnya `warung-agent`.
3. Unduh JSON credential secara lokal.
4. Beri service account akses **Editor** pada spreadsheet Warung.
5. Jangan commit JSON credential.

Sheet yang dibaca pada PHASE 1:

- `Produk`: `Product ID`, `Nama Produk`, `Kategori`, `Satuan`, `Harga Jual`, `Harga Modal`, `Stok`, `Stok Minimum`, `Aktif`, `Catatan`

Harga dan stok harus disimpan sebagai angka Sheets, bukan string berformat mata uang.

## Environment

Salin `.env.example` menjadi `.env`, lalu isi spreadsheet ID asli:

```text
GOOGLE_CREDENTIALS_PATH=credentials/google-service-account.json
GOOGLE_SPREADSHEET_ID=your-real-spreadsheet-id
```

`.env` dan `credentials/*.json` diabaikan oleh Git. Aplikasi tidak menampilkan credential dalam response.

## Local development

Python 3.11+ direkomendasikan.

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env
```

Jangan jalankan `app.main` sebelum `.env` dan credential asli tersedia. Entry point tersebut membuat client Sheets dan akan gagal dengan pesan konfigurasi yang aman jika environment belum lengkap:

```bash
.venv/bin/python -m app.main
```

## Testing

Unit test memakai fake Sheets gateway dan tidak membutuhkan credential Google:

```bash
.venv/bin/pytest -q
```

Test PHASE 1 mencakup pencarian produk aktif, produk tidak ditemukan, status stok, dan structured error.

## PHASE 1 operations

Contoh penggunaan Python:

```python
from app.products import ProductRepository, ProductService
from app.sheets import GoogleSheetsClient

service = ProductService(ProductRepository(client))
service.search_product("aqua")
service.get_product("P002")
service.get_stock("P002")
```

Contoh hasil error:

```json
{
  "success": false,
  "error_code": "PRODUCT_NOT_FOUND",
  "message": "Product P999 tidak ditemukan."
}
```

## PHASE 2 operations

Transaksi selalu mengambil harga terbaru dari `Produk.Harga Jual`; field `price` dari caller diabaikan. Semua validasi dilakukan sebelum write.

```python
from app.transactions import InMemoryIdempotencyStore, TransactionIdGenerator, TransactionService
from app.stock import StockService

transaction_service = TransactionService(
  products, client, TransactionIdGenerator(client), InMemoryIdempotencyStore(), clock
)
transaction_service.create_transaction(
  items=[{"product_id": "P002", "qty": 2}],
  payment_method="Tunai",
  idempotency_key="telegram-update-123",
)

StockService(products, client, clock).add_stock(
  product_id="P002", qty=20, reference="PO-001", note="Restock"
)
```

Penjualan menambahkan row pada `Transaksi` dan `Detail_Transaksi`, mengurangi `Produk.Stok`, lalu menulis `SALE` dengan qty negatif ke `Stok_Log`. Restock menambah stok dan menulis `PURCHASE` dengan qty positif.

`InMemoryIdempotencyStore` mencegah request dengan key yang sama membuat transaksi kedua selama proses berjalan. Implementasi production nantinya perlu store persisten dan mekanisme reservation/lock untuk concurrent requests.

## PHASE 3 reporting dan stock monitoring

`ReportingService` menyediakan `get_daily_sales`, `get_sales_summary`, `get_product_sales`, `get_category_sales`, `get_payment_summary`, `get_stock_status`, `get_low_stock`, `get_out_of_stock`, dan `get_stock_movements`. Laporan penjualan memakai snapshot `Detail_Transaksi`, bukan katalog produk saat ini. Setiap operasi membaca sheet yang diperlukan satu kali dan tidak melakukan N+1 request.

Average transaction value menggunakan integer division (`revenue // transaction_count`), sehingga pecahan dibulatkan ke bawah. Tanggal input harus berformat `YYYY-MM-DD`.

Contoh daily sales:

```json
{"date": "2026-09-08", "transaction_count": 12, "total_items": 35, "revenue": 485000}
```

Contoh low-stock output:

```json
[{"product_id": "P002", "nama": "Aqua 600ml", "stok": 8, "stok_minimum": 10, "status": "LOW"}]
```

Data sheet yang korup menghasilkan structured error seperti `INVALID_DATE`, `INVALID_PRODUCT_DATA`, `INVALID_TRANSACTION_DATA`, atau `INVALID_STOCK_DATA`; data tidak dikonversi diam-diam menjadi nol.

## PHASE 4 integration

MCP memakai Python SDK v2 `MCPServer` dengan stdio transport. Tool yang tersedia:

`search_product`, `get_product`, `get_stock`, `create_transaction`, `add_stock`, `get_daily_sales`, `get_sales_summary`, `get_product_sales`, `get_category_sales`, `get_payment_summary`, `get_stock_status`, `get_low_stock`, `get_out_of_stock`, dan `get_stock_movements`.

MCP tidak membaca Sheets langsung dan tidak mengandung business logic. Jalankan MCP server setelah `.env` dan credential Sheets tersedia:

```bash
.venv/bin/python -m app.main --mcp
```

Gemini dikonfigurasi melalui `GEMINI_API_KEY` dan `GEMINI_MODEL`. Model hanya memilih tool dan menyusun respons; harga, stok, total, ID, dan status transaksi berasal dari service melalui MCP adapter.

Telegram text bot memakai `python-telegram-bot` dan `TELEGRAM_BOT_TOKEN`:

```bash
.venv/bin/python -m app.main --telegram
```

Setiap update Telegram menggunakan `telegram:<update_id>` sebagai idempotency key. Handler hanya menerima text message dan tidak mengandung logic transaksi.

### Pending transaction state

Untuk laporan penjualan tanpa metode pembayaran, Telegram menyimpan state sementara per `chat_id` di memory:

```text
PendingTransaction(items, payment_method=None, status="WAITING_PAYMENT", created_at=...)
```

State berlaku 10 menit, tidak disimpan ke Google Sheets, dan hanya menyimpan product ID, qty, metode pembayaran, status, serta timestamp. `tunai`, `transfer`, atau `qris` melanjutkan transaksi; `batal` atau `cancel` menghapusnya. Pesan intent baru seperti `stok aqua` diproses terpisah tanpa menggabungkan state. State dibersihkan setelah service transaksi berhasil atau gagal, sehingga tidak ada retry otomatis yang berisiko menggandakan transaksi.

Unit tests boundary tidak memanggil API Gemini, Telegram, atau Google asli:

```bash
.venv/bin/pytest -q
```

### Manual E2E checklist

Dengan credential nyata dan bot aktif, verifikasi:

1. `jual aqua 2` dengan payment method yang disebutkan menghasilkan transaksi, pengurangan stok, dan `SALE` log.
2. Qty melebihi stok menghasilkan `INSUFFICIENT_STOCK` dan tidak mengklaim sukses.
3. `barang hampir habis` memanggil `get_low_stock`.
4. `omzet hari ini` memanggil `get_daily_sales`.
5. Update Telegram yang sama dua kali hanya menghasilkan satu transaksi, satu pengurangan stok, dan satu stock log.

E2E nyata belum dijalankan di lingkungan ini karena tidak ada credential Google, API key Gemini, atau token Telegram yang boleh digunakan untuk testing.

## Docker

`docker-compose.yml` hanya menyediakan environment runtime dan mount credential read-only. Credential tetap harus dibuat lokal; image tidak menyertakannya.

```bash
docker compose run --rm warung-agent
```

## Security

- Jangan hardcode credential, API key, atau spreadsheet ID.
- Jangan commit `.env` atau service-account JSON.
- Jangan mengekspos object Google API atau response internal ke agent.
- MCP nantinya hanya boleh mengekspos operasi bisnis, bukan arbitrary cell/API operations.

## Roadmap

1. Production persistence/locking untuk idempotency dan transaction ID.
2. Historical cost sebelum profit reporting production-ready.
3. Hardening deployment, observability, dan authorization MCP remote bila diperlukan.

Google Sheets tidak menyediakan transaction semantics seperti database relasional. PHASE 2 memvalidasi semua data sebelum menulis dan mengembalikan `TRANSACTION_RECONCILIATION_REQUIRED` atau `STOCK_WRITE_FAILED` jika tahapan write gagal. Row yang sudah tertulis tidak dipalsukan rollback; reconciliation manual tetap diperlukan. Idempotency conflict dikembalikan sebagai `IDEMPOTENCY_CONFLICT` tanpa efek samping kedua. Historical cost belum disimpan; sebelum profit reporting production-ready, tambahkan `Harga Modal Saat Transaksi` ke `Detail_Transaksi`.
