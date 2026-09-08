# 🏪 Asisten Kasir Warung Madura (AI Telegram Bot)

Asisten pintar berbasis AI untuk pemilik **Warung Madura**. Cukup kirim pesan di **Telegram** seperti ngobrol biasa, semua catatan penjualan, stok barang, barang masuk (kulakan), pemakaian sendiri, dan laporan omzet langsung tercatat otomatis dan rapi di **Google Sheets**.

Tidak perlu aplikasi kasir yang ribet atau mesin kasir mahal. Pemilik warung cukup pakai HP dan mengetik bahasa sehari-hari!

---

## ✨ Kemampuan Utama

* 🗣️ **Paham Bahasa Sehari-hari**: Tidak perlu menghafal kode perintah seperti `/help`, `/start`, atau tombol kaku. Ketik saja seperti ngomong ke kasir.
* 📒 **Buku Kas Otomatis di Google Sheets**: Semua transaksi langsung tersimpan rapi di Google Sheets, bisa dicek langsung dari HP kapan saja dan di mana saja.
* 🍜 **Pintar Membedakan Barang**: Kalau mengetik barang yang punya banyak varian (misal *"indomie"*), bot akan bertanya ramah: *"Indomie yang mana Bos? Goreng atau Soto?"*.
* 💳 **Mendukung Berbagai Cara Bayar**: Catat bayar **Tunai**, **Transfer**, atau **QRIS**. Kalau lupa sebut cara bayar, bot akan mengingatkan dengan ramah.
* 🔒 **Aman dari Salah Catat (Dobel Input)**: Bot menjaga agar pesan yang terkirim dua kali tidak mencatat transaksi berulang.

---

## 💬 Contoh Cara Ngobrol dengan Bot

Pemilik warung atau penjaga toko cukup mengetik seperti ini di Telegram:

### 1. 🛒 Catat Penjualan
> **Bos:** `terjual 2 indomie goreng tunai`  
> **Bot:** Siap Bos! 2 Indomie Goreng Spesial sudah dicatat (Tunai). Total Rp6.000.  
>
> *(Kalau tidak sebut cara bayar)*  
> **Bos:** `jual 1 aqua`  
> **Bot:** Siap Bos, penjualan sudah dicatat sementara. Bayarnya Tunai, Transfer, atau QRIS?  
> **Bos:** `tunai dong`  
> **Bot:** Siap Bos! Penjualan Aqua 600ml sudah dicatat Tunai.

### 2. 📦 Cek Stok Barang
> **Bos:** `stok rokok marlboro tinggal berapa?`  
> **Bot:** Stok Marlboro Filter Black sisa 12 bungkus, Bos.  
>
> **Bos:** `barang apa aja yang mau habis?`  
> **Bot:** Ini barang yang stoknya menipis, Bos: Telur Ayam (sisa 3 butir), Aqua 600ml (sisa 4 botol).

### 3. ➕ Catat Kulakan / Barang Masuk
> **Bos:** `indomie masuk 2 kardus`  
> **Bot:** Siap Bos! Stok Indomie Goreng berhasil ditambah 80 bungkus.

### 4. 🍜 Catat Barang Dipakai Sendiri
> **Bos:** `aku ambil 1 indomie buat makan`  
> **Bot:** Dicatat Bos, 1 Indomie dipakai sendiri. Stok sudah dikurangi tanpa masuk omzet kasir.

### 5. 💰 Cek Omzet & Penjualan Hari Ini
> **Bos:** `omzet hari ini berapa?`  
> **Bot:** Laporan penjualan hari ini: Total 18 transaksi, 42 barang terjual. Total omzet Rp245.000, Bos!

---

## 📋 Struktur Buku Warung (Google Sheets)

Semua data tersimpan di spreadsheet Google Sheets Anda dengan tab-tab berikut:

1. **Produk**: Daftar barang, harga jual, harga modal, stok, dan batas stok minimum.
2. **Transaksi**: Riwayat nota penjualan beserta tanggal dan metode pembayaran.
3. **Detail_Transaksi**: Rincian produk apa saja yang dibeli pada setiap transaksi.
4. **Stok_Log**: Catatan keluar-masuk stok barang (penjualan, kulakan, atau barang terpakai).

---

## 🚀 Panduan Memulai (Setup Singkat)

### 1. Kebutuhan Awal
* Komputer / Server dengan **Python 3.11+**.
* Akun **Google Cloud** dengan akses Google Sheets API (menggunakan *Service Account*).
* Spreadsheet Google Sheets yang sudah di-share akses **Editor** ke email service account.
* Token Bot Telegram dari [@BotFather](https://t.me/botfather).
* API Key Google Gemini AI dari [Google AI Studio](https://aistudio.google.com/).

### 2. Pemasangan

1. **Unduh dan pasang dependensi:**
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

2. **Atur konfigurasi (.env):**
   Salin berkas `.env.example` menjadi `.env`:
   ```bash
   cp .env.example .env
   ```
   Lalu buka berkas `.env` dan isi data Anda:
   ```ini
   # Kunci Google Sheets
   GOOGLE_CREDENTIALS_PATH=credentials/google-service-account.json
   GOOGLE_SPREADSHEET_ID=masukkan_id_spreadsheet_anda_disini

   # Kunci AI & Telegram
   GEMINI_API_KEY=masukkan_api_key_gemini_anda
   TELEGRAM_BOT_TOKEN=masukkan_token_bot_telegram_anda
   ```

3. **Jalankan Bot:**
   ```bash
   python -m app.main --telegram
   ```
   Buka bot Anda di Telegram, lalu sapa dengan: `Halo!` atau langsung ketik transaksi pertama Anda!

---

## 🛠️ Informasi untuk Pengembang (Developer Notes)

Bagi pengembang yang ingin memodifikasi atau menguji sistem:

* **Menjalankan Tes Otomatis (Unit & Integration Tests):**
  ```bash
  .venv/bin/pytest -q
  ```
  *(Pengujian menggunakan mock data, tidak memotong kuota API Google maupun Telegram).*

* **Menjalankan Mode MCP (Model Context Protocol):**
  ```bash
  .venv/bin/python -m app.main --mcp
  ```

* **Menjalankan via Docker:**
  ```bash
  docker compose run --rm warung-agent
  ```

---

*Dibuat untuk memudahkan wirausaha dan UMKM warung mengelola usaha dengan bantuan kecerdasan buatan tanpa ribet.* 🇮🇩
