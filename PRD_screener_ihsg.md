# PRD — Screener IHSG Otomatis (screener_ihsg)
**Versi:** 1.0 — 27 September 2026
**Ditulis untuk:** AI coding agent (Antigravity CLI, Gemini 3.8 Flash) di `~/projects/screener_ihsg`
**Ditulis oleh:** Claude, berdasarkan diskusi dengan Tubagus Budi (product owner & end user)

---

## 1. Ringkasan Eksekutif

Bangun sistem screening saham IHSG semi-otomatis yang mereplikasi alur kerja bot Telegram
`@chart_saham_bot` (yang user pernah berlangganan, sekarang tidak lagi), memanfaatkan **MCP server
`idx-edge`** (IDX EDGE PRO API, `stock.arjum.com`) yang sudah terpasang dan terautentikasi di
Antigravity CLI sebagai sumber data utama — bukan Yahoo Finance seperti percobaan sebelumnya
(`SmartScreener_v2`).

Alur kerja target: **Sektor (top-down) → RRG → Screening kandidat → Validasi mendalam → Trade plan
→ eksekusi/alert**, dengan output akhir berupa daftar saham yang lolos filter beserta rencana
trading (entry, target, cutloss) yang bisa langsung dieksekusi user.

---

## 2. Latar Belakang & Riwayat

Konteks penting yang harus dipahami agent sebelum membangun, supaya tidak mengulang kesalahan lama:

1. **Percobaan pertama (`SmartScreener_v2`, Google Apps Script + Yahoo Finance)** — dibangun
   sendiri oleh user sebelum proyek ini. Punya sistem scoring 10-komponen (Volume/Liquidity 25pt,
   Money Flow/Foreign 30pt, Trend/Momentum 25pt, Fundamentals 20pt) dengan band STRONG BUY/
   WATCHLIST/TUNGGU/AVOID. **Proyek ini sudah tidak dipakai lagi**, tapi ada pelajaran penting dari
   bug-bug yang muncul (lihat §8 Lessons Learned) — JANGAN diulang.
2. **Eksplorasi kedua (semi-manual, Google Sheets + Stockbit)** — dilakukan paralel di sesi chat
   lain, menghasilkan template 7-sheet (`Panduan`, `1_Sektor`, `2_Screening`, `3_ForeignFlow`,
   `4_BrokerSummary`, `5_Validasi`, `6_TradePlan`) yang formula-nya sudah tervalidasi jalan. Template
   ini **bukan untuk dibangun ulang**, tapi struktur & pemetaan datanya (§6) berguna sebagai referensi
   skema output.
3. **Sekarang (proyek ini, `screener_ihsg`)** — pivot ke otomasi penuh karena user sudah punya akses
   API resmi (`idx-edge` MCP) yang menyediakan data yang sebelumnya harus dikumpulkan manual dari
   Stockbit (foreign flow, broker summary) atau tidak bisa didapat sama sekali (order flow/tick-level).

**Penting:** bot Telegram sumber acuan menghitung satu angka **Money Flow (MF)** gabungan dari
klasifikasi seluruh transaksi (semua investor). Belum dikonfirmasi apakah `idx-edge` API menyediakan
metrik yang identik dengan ini — perlu dicek langsung ke dokumentasi/response API sebelum
mengasumsikan field itu ada (lihat §9 Pertanyaan Terbuka).

---

## 3. Tujuan Produk

- Menyediakan daftar kandidat saham harian (top-down dari sektor) yang lolos kriteria likuiditas,
  momentum, dan aliran dana (asing & broker).
- Menyajikan analisa mendalam per saham (fundamental + teknikal + aliran dana) plus rencana trading
  (entry range, target, cutloss, R:R) — setara `/analisa` bot.
- Meminimalkan input manual: begitu MCP tool tersedia, tarik data via API, bukan copy-paste dari
  platform lain.
- Berjalan sebagai **tool/CLI/script yang dijalankan on-demand oleh user** (bukan aplikasi web
  berjalan 24 jam) — konsisten dengan preferensi user untuk sistem yang ringan, tidak perlu
  server/hosting.

## 4. Non-Goals (Di Luar Cakupan v1)

- **Alert real-time otomatis** — user sudah punya fitur alert bawaan Stockbit; sistem ini tidak
  perlu membangun ulang mekanisme alert. (Boleh jadi stretch goal fase lanjut jika user minta.)
- **Eksekusi order otomatis (auto-trading)** — tidak diminta, dan berisiko; jangan dibangun.
- **Replikasi 100% tampilan visual bot Telegram** (chart custom dengan watermark, dsb) — cukup
  fungsinya (angka & kesimpulan), bukan tampilannya.
- **Analisis tick-level penuh (`/tda`, `/tfa`)** — masuk sebagai **stretch goal Fase 3**, bukan
  syarat wajib rilis awal, karena metodologi replikasinya (cluster jam transaksi, hidden flow) belum
  divalidasi bisa dibangun dari `done_details`.

---

## 5. Sumber Data: MCP `idx-edge`

MCP server sudah terpasang & terautentikasi di Antigravity (`✓ idx-edge` pada `Plugins`). 15 tools
tersedia; yang teridentifikasi dari dokumentasi/screenshot:

| Tool | Fungsi | Dipakai di modul |
|---|---|---|
| `screener_saham_terkini` | Screening saham dengan kriteria | Modul Screening (§7.3) |
| `analisa_saham` | Analisa komprehensif 1 saham (fundamental+teknikal) | Modul Validasi (§7.4) |
| `broker_summary` | Rekap broker + **foreign flow** (buy/sell/net asing) per saham | Modul Foreign Flow & Broker (§7.4) |
| `akumulasi_broker_historis` | Akumulasi broker/asing multi-hari | Modul Foreign Flow & Broker (§7.4) |
| `riwayat_harga` | OHLCV historis per saham | Modul RRG, Chart, Pivot (§7.2, §7.5) |
| `laporan_keuangan` | Laporan keuangan/fundamental | Modul Validasi (§7.4) |
| `done_details` | Rincian order flow / done match (tick-level) | Stretch — Modul Order Flow (§7.6) |
| `market_cap` | Ranking market cap | Modul Sektor/Screening (opsional) |
| `search` | Cari kode saham | Utility |
| `seasonality_bulanan` | Pola musiman bulanan | Nice-to-have, tidak wajib v1 |
| `insider_transaksi` | Transaksi insider | Nice-to-have, tidak wajib v1 |
| `harga_realtime` | Harga real-time 1 saham | Utility |
| `batch_price` / `batch_analysis` | Versi batch dari harga/analisa | Optimasi kuota (§8) |
| *(+ 1-2 tool lain belum teridentifikasi)* | — | Agent harus inventarisir daftar tool lengkap di awal kerja (lihat §10 Langkah Awal) |

**Tidak ada tool eksplisit untuk heatmap sektor ber-filter Money Flow** seperti `/heatmap index mf`
bot. Ini harus **dihitung/agregasi sendiri** oleh sistem (kumpulkan data per saham dalam satu
sektor via `screener_saham_terkini`/`batch_analysis`, agregasi berdasarkan mapping sektor).

---

## 6. Pemetaan Alur Bot → Fitur Sistem

Alur acuan (dari dokumentasi bot & log penggunaan riil yang sudah dianalisis):

| # | Command Bot | Tahap | Rencana di Sistem Ini |
|---|---|---|---|
| 1 | `/heatmap index mf w` | 1. Sektor | Agregasi harian per sektor dari data saham anggota (proksi; MF asli belum pasti tersedia — lihat §9) |
| 2 | `/rrg <sektor>` | 1. Sektor | RRG engine: hitung RS-Ratio/RS-Momentum dari `riwayat_harga` (saham anggota sektor vs benchmark), plot & rank Leading/Improving/Weakening/Lagging |
| 3 | `/scr sector=X + val>1mil + vol>ma20vol + mf>0 + nbsa>0` | 2. Screening | `screener_saham_terkini` dengan kriteria setara; `mf>0` diganti/dilengkapi kriteria dari `broker_summary` jika field MF tidak ada |
| 4 | `/analisa <kode>` | 3. Validasi | `analisa_saham` + `laporan_keuangan`, hasilkan ringkasan fundamental+teknikal+trade plan (entry/TP/CL) |
| 5 | `/accummf <kode> 5` | 3. Validasi | **Cek dulu apakah `broker_summary`/tool lain punya field MF** — jika tidak ada, dokumentasikan sebagai gap, jangan dipalsukan |
| 6 | `/accumnbsa <kode> 5/10/20` | 3. Validasi | `akumulasi_broker_historis` (rolling window sesuai parameter) |
| 7 | `/tda <kode>` | 3. Validasi | Stretch (Fase 3) — dari `done_details`, jika formatnya memungkinkan analisis cluster |
| 8 | `/c <kode> mt` | 3. Validasi | `riwayat_harga` multi-timeframe (daily/weekly minimal), hitung trend & rangkuman |
| 9 | `/pivot <kode> next` | 4. Eksekusi | Hitung pivot standar (P, R1-R3, S1-S3) dari OHLC harian terakhir via `riwayat_harga` |
| 10 | `/alert` | 4. Eksekusi | **Di luar cakupan** — user pasang manual di Stockbit |

---

## 7. Functional Requirements

### 7.1 Struktur Output
Output harian minimal berupa **1 file terstruktur** (format bebas dipilih agent — Markdown/HTML/CSV,
sesuai kemudahan baca user) berisi: ringkasan sektor top-down → daftar kandidat lolos screening →
detail validasi per kandidat → trade plan.

### 7.2 Modul Sektor & RRG
- Input: daftar 11 sektor IDX (Energy, Basic Materials, Industrials, Consumer Non-Cyclicals,
  Consumer Cyclicals, Healthcare, Financials, Properties & Real Estate, Technology,
  Infrastructures, Transportation & Logistic) dengan daftar saham anggota per sektor (agent perlu
  menyusun/menyimpan mapping ini — cek apakah `idx-edge` punya endpoint untuk ini, atau perlu
  disusun manual sekali dan disimpan sebagai config).
- Hitung RS-Ratio & RS-Momentum (metodologi JdK RRG) untuk saham dalam 1 sektor vs benchmark
  (Composite/IHSG), pakai `riwayat_harga` (minimal 60-90 hari histori).
- Output: klasifikasi tiap saham ke kuadran Leading/Improving/Weakening/Lagging.

### 7.3 Modul Screening Kandidat
- Gunakan `screener_saham_terkini` dengan filter dasar: likuiditas (value transaksi), volume vs
  MA20, dan (jika tersedia) foreign net buy.
- Filter berbasis sektor: hanya proses saham dari sektor yang lolos tahap RRG (Leading/Improving).

### 7.4 Modul Validasi Mendalam
Untuk setiap kandidat final (idealnya dibatasi 1-5 saham per hari untuk hemat kuota):
- Fundamental & valuasi: `analisa_saham` + `laporan_keuangan` (PBV, PER, EPS, NAV, growth,
  DER, dividend yield).
- Foreign flow: `broker_summary` (harian) + `akumulasi_broker_historis` (5D/10D/20D rolling).
- Broker action: dari `broker_summary` — top buyer/seller broker & indikasi akumulasi/distribusi.
- Teknikal: `riwayat_harga` untuk trend daily/weekly, ATR, support/resistance.
- Trade plan: hitung buy range, cutloss, target 1 & 2, R:R — **gunakan ATR asimetris untuk TP vs CL**
  (lihat §8, bug lama R:R selalu 1:1 karena ATR simetris — jangan diulang).

### 7.5 Modul Pivot
- Hitung pivot standar harian dari OHLC hari terakhir (`riwayat_harga`): Pivot=(H+L+C)/3,
  R1=2P-L, S1=2P-H, R2=P+(H-L), S2=P-(H-L), dst.

### 7.6 [Stretch — Fase 3] Modul Order Flow
- Eksplorasi `done_details`: cek apakah data tick-level cukup detail (timestamp, harga, volume,
  klasifikasi buy/sell) untuk mendeteksi cluster smart money & breakout/reversal seperti `/tda`.
  **Jangan dibangun sebelum data mentahnya diperiksa** — cek dulu 1 contoh response.

---

## 8. Non-Functional Requirements & Lessons Learned

**Kuota API:**
- Dashboard menunjukkan **1.000 req/jam**; user menyebut secara verbal "1.000 req per hari" —
  **ADA KETIDAKCOCOKAN, harus dikonfirmasi dulu** (cek response header/dokumentasi resmi) sebelum
  agent mendesain strategi caching/batching. Desain sistem harus tetap hemat kuota terlepas dari
  mana yang benar:
  - Gunakan `batch_price`/`batch_analysis` bila memproses banyak saham sekaligus, bukan loop per
    saham.
  - Cache hasil `riwayat_harga` per hari (jangan tarik ulang data yang sama dalam 1 sesi run).
  - Batasi jumlah saham yang diproses di tahap Validasi Mendalam (§7.4) ke kandidat yang benar-benar
    lolos tahap Screening.

**Jangan ulangi bug dari `SmartScreener_v2`:**
1. R:R selalu 1.0:1 — karena multiplier ATR untuk Target dan Cutloss dibuat simetris. Pastikan
   target profit dan cutloss punya rasio berbeda (misal cutloss 1x ATR, target 1.5-2x ATR).
2. Hasil kosong (zero STRONG BUY) karena sheet Fundamental kosong / cold-start Money Flow history —
   pastikan sistem baru punya fallback yang jelas kalau data belum lengkap (jangan diam-diam
   menghasilkan 0 hasil tanpa keterangan).
3. Runtime crash dari variabel undefined — testing dasar (unit test kecil / smoke test) sebelum
   dianggap selesai.

**Kejujuran data:**
- Jangan membuat field/angka yang datanya sebenarnya tidak tersedia dari API (contoh: kalau field
  Money Flow murni tidak ada, jangan dihitung manual dengan asumsi kasar dan diberi label seolah
  sama dengan MF bot — beri label jujur, misal "Net Foreign Flow" bukan "Money Flow").

---

## 9. Pertanyaan Terbuka / Perlu Diverifikasi Sebelum Implementasi Penuh

1. **Kuota**: 1.000 req/jam atau /hari? (lihat §8)
2. **Field Money Flow**: apakah ada field murni "money flow" (klasifikasi semua transaksi, bukan
   cuma asing) di salah satu tool `idx-edge`? Cek response `broker_summary` & `analisa_saham` secara
   langsung.
3. **Mapping sektor→saham**: apakah `idx-edge` punya tool untuk daftar saham per sektor, atau perlu
   disusun manual dan disimpan sebagai file config statis?
4. **`done_details`**: format & granularitas datanya seperti apa? Ini menentukan apakah Modul Order
   Flow (§7.6) realistis dikerjakan.
5. **5 tool `idx-edge` yang belum teridentifikasi namanya** — agent perlu memanggil daftar tool
   lengkap dari MCP di awal kerja.

---

## 10. Langkah Awal yang Disarankan untuk Agent

1. Inventarisir semua 15 tool `idx-edge` (nama, parameter, contoh response) — jangan asumsikan dari
   dokumentasi saja, panggil langsung dengan 1 saham contoh untuk tiap tool inti.
2. Jawab §9 Pertanyaan Terbuka berdasarkan hasil inventarisir di atas.
3. Bangun Modul Screening (§7.3) & Modul Pivot (§7.5) dulu — paling sedikit dependensi/risiko.
4. Bangun Modul RRG (§7.2) — butuh mapping sektor→saham (§9.3) selesai dulu.
5. Bangun Modul Validasi (§7.4) — paling banyak field, kerjakan setelah §9.2 terjawab.
6. Modul Order Flow (§7.6) dikerjakan terakhir, hanya jika §9.4 menunjukkan itu layak.
7. Setiap modul: buat smoke test kecil sebelum lanjut ke modul berikutnya (hindari bug #3 di §8).
