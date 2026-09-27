# Kamus Metrik & Kejujuran Sumber Data `screener_ihsg`

Dokumen ini disusun untuk memenuhi prinsip **Kejujuran Data (PRD §8)**. Seluruh istilah, metrik, label sinyal, dan probabilitas yang dihasilkan oleh sistem `screener_ihsg` didokumentasikan sumber asal, definisi, dan formula perhitungannya secara transparan.

---

## 1. Kategori Sinyal Pasar (Signal Buckets)

Semua label kategori sinyal di bawah ini dihasilkan oleh model analisis server **`idx-edge`** pada endpoint `screener_saham_terkini` (`screener_v5.py`):

| Kategori Sinyal | Definisi & Kriteria Logika | Implikasi Taktis |
|---|---|---|
| **🟢 SINYAL BERSIH** | Konvergensi tiga faktor secara bersamaan: (1) teknikal bullish (harga berada di atas SMA5 dan SMA20), (2) lonjakan akumulasi broker utama, dan (3) net buy investor asing signifikan tanpa ada indikasi distribusi terdeteksi. | **Prioritas Utama (Top Pick).** Setup paling ideal untuk *buy on weakness* atau *trend continuation*. |
| **🥷 SINYAL SENYAP** | Terjadi konsentrasi akumulasi pekat oleh broker kakap atau asing saat pergerakan harga saham masih tenang/konsolidasi (belum mengalami lonjakan volatilitas harga). | **Prioritas Akumulasi Awal.** Peluang entry sebelum saham mengalami *breakout*. |
| **🥷 AKUMULASI SENYAP** | Sinyal tier-2 yang mendeteksi aliran dana masuk ke saham tertentu, tetapi salah satu parameter sekunder (seperti volume transaksi atau histori win rate) belum memenuhi ambang batas sinyal bersih. | **Watchlist Cadangan.** Dipantau hingga ada konfirmasi lonjakan volume pada sesi berikutnya. |
| **🩸 RISIKO PANTULAN** | Harga saham melonjak saat volume tinggi, namun broker summary menunjukkan aksi jual bersih (*net sell*) oleh broker besar. Merupakan jebakan pantulan teknikal sesaat (*dead-cat bounce*). | **Dihindari / Diberi Penalti Skor.** Disaring keluar dari daftar kandidat utama. |
| **⚔️ KONFLIK DISTRIBUSI** | Harga saham berada di atas rata-rata bergerak (MA), namun investor asing atau top broker melakukan distribusi agresif secara berlawanan. | **Dihindari / Sangat Berisiko.** Potensi pembalikan arah tajam saat akumulasi semu berhenti. |

---

## 2. Metrik Probabilitas Historis (Personality Engine)

Setiap saham diuji terhadap model *event-based backtesting* yang mengamati seluruh kemunculan pola serupa sejak **Januari 2020**:

### A. WR Event (Win Rate Event)
- **Definisi:** Persentase probabilitas historis bahwa harga saham akan menyentuh level **Target Profit** (berbasis volatilitas ATR dinamis) sebelum menyentuh level **Stop Loss**.
- **Horizon Waktu (Holding Time):** Rata-rata posisi ditutup antara **D+2 hingga D+4** hari bursa.
- **Formula:**
  $$\text{WR Event} = \frac{\text{Jumlah Kejadian Menyentuh TP}}{\text{Total Kejadian Pola Serupa}} \times 100\%$$
- **Ambang Batas Kualitas:**
  - $> 70\%$: Sangat Tinggi (*Strong Statistical Edge*)
  - $60\% - 70\%$: Positif (*Favorable Edge*)
  - $< 50\%$: Lemah (Probabilitas kalah lebih besar dari probabilitas menang)

### B. Potensi (Maximum Favorable Excursion)
- **Definisi:** Estimasi rata-rata persentase kenaikan harga tertinggi yang tercapai secara historis setelah pola sinyal tersebut terdeteksi.
- **Formula:**
  $$\text{Potensi (\%)} = \text{Rata-rata}\left(\frac{\text{Harga Tertinggi Tercapai} - \text{Harga Entry}}{\text{Harga Entry}} \times 100\%\right)$$

### C. DD (Drawdown / Maximum Adverse Excursion)
- **Definisi:** Estimasi rata-rata persentase penurunan harga terdalam yang dialami selama masa *holding* sebelum target tercapai.
- **Fungsi Praktis:** Menjadi dasar penentuan toleransi *noise* harga agar tidak memasang stop-loss terlalu ketat yang rentan terkena *false breakdown*.

---

## 3. Net Foreign Flow vs Istilah "Money Flow"

Sesuai evaluasi pada PRD §8, sistem `screener_ihsg` **tidak menggunakan istilah "Money Flow" (MF)** karena API `idx-edge` tidak menyediakan indikator agregat money flow tertutup seperti bot Telegram lama.

- **Sumber Data Riil:** `idx-edge:riwayat_harga` (field `n_foreign`) dan `idx-edge:broker_summary` (parameter `flow="F"`).
- **Definisi:** Selisih riil antara volume pembelian asing (`f_buy`) dikurangi volume penjualan asing (`f_sell`) dalam satuan lembar saham:
  $$\text{Net Foreign Flow} = \text{Foreign Buy Shares} - \text{Foreign Sell Shares}$$
- **Penyajian Data:**
  - Ditampilkan dalam tabel harian 5 hari ke belakang (D-0 hingga D-4).
  - Berlabel transparan: **Net Foreign Flow (shares)** dengan keterangan arah **BUY** atau **SELL**.

---

## 4. Metodologi Trade Plan & Proteksi Risiko (Pivot + ATR)

Berdasarkan audit teknikal, Trade Plan diturunkan langsung dari struktur harga aktual:

### A. Rentang Beli (Entry Range)
- **Batas Atas (`entry_high`):** Harga penutupan terakhir (`Close`).
- **Batas Bawah (`entry_low`):** Level Support terdekat ($S1$) jika $S1 < Close$, atau $Close - 0.5 \times ATR$.

### B. Batas Rugi (Cutloss Invariant)
- **Aturan Mutlak:** $\text{Cutloss} < \text{Entry Low}$.
- **Penyesuaian Level:** Jika jarak $Close - ATR$ jatuh di dalam atau di atas $\text{entry\_low}$ (seperti kasus volatilitas rendah pada saham tertentu), cutloss diturunkan ke level Support $S2$ atau diberikan buffer pengaman $\text{entry\_low} - 0.5 \times ATR$.

### C. Target Profit (TP1 & TP2)
- Diturunkan dari level Resisten Pivot aktual:
  - Jika $R1 \ge Close + 0.4 \times ATR$, maka **Target 1 = $R1$** dan **Target 2 = $R2$**.
  - Jika harga sudah dekat dengan $R1$, maka **Target 1 = $R2$** dan **Target 2 = $R3$**.

### D. Rasio Risk-to-Reward (R:R) Dinamis
- Dihitung dari titik tengah area pembelian rata-rata ($\text{entry\_mid}$):
  $$\text{Risk} = \text{entry\_mid} - \text{Cutloss}$$
  $$\text{Reward} = \text{Target 1} - \text{entry\_mid}$$
  $$\text{R:R Ratio} = \frac{\text{Reward}}{\text{Risk}}$$
- **Sifat:** Bervariasi dinamis antar saham sesuai jarak support-resistance riil masing-masing emiten (tidak lagi kaku 1.5:1).

---

## 5. Metrik Fundamental & Valuasi

Disarikan dari tool `idx-edge:laporan_keuangan` (`INCOME_STATEMENT` dan `BALANCE_SHEET`):

1. **EPS (Earning Per Share):** Laba per saham dasar yang diatribusikan kepada entitas induk dari laporan laba rugi kuartal terakhir.
2. **PER (Price to Earnings Ratio):** Dihitung dari $\frac{\text{Harga Terakhir}}{\text{EPS Tahunan (EPS Kuartal} \times 4)}$.
3. **DER (Debt to Equity Ratio):** Rasio solvabilitas dari $\frac{\text{Total Liabilitas}}{\text{Total Ekuitas}}$.
4. **Pertumbuhan Pendapatan (Revenue Growth YoY):** Persentase perubahan penjualan bersih periode berjalan dibanding periode yang sama tahun sebelumnya.
5. **Pertumbuhan Laba Bersih (Net Income Growth YoY):** Persentase perubahan laba bersih periode berjalan dibanding periode yang sama tahun sebelumnya.

---

## 6. Prinsip Penanganan Data Kosong (Fallback Transparency)

Sistem **dilarang menyembunyikan kegagalan data atau memberikan teks kosong tanpa alasan**. Jika sebuah saham dalam daftar tidak memiliki detail validasi:
- Sistem wajib menyatakan alasan spesifik:
  - Apakah karena kuota harian dialokasikan untuk saham prioritas utama (top tier)?
  - Apakah emiten belum merilis laporan keuangan periode terbaru di bursa?
  - Apakah terjadi kendala timeout pada endpoint server?
