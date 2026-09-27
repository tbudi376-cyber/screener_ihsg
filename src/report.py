from datetime import datetime
from pathlib import Path
from src.models import Candidate, ValidationResult
from src.validator import format_validation_summary


def generate_daily_report(
    date: str,
    sector_ranking: list[tuple],
    candidates: list[Candidate],
    validations: list[ValidationResult],
    quota_used: int,
) -> str:
    lines = []
    lines.append(f"# Screener IHSG - Laporan Harian {date}")
    lines.append(f"_Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}_")
    lines.append(f"_Kuota API terpakai: {quota_used} request_")
    lines.append("")
    lines.append("---")
    lines.append("")

    lines.append("## 1. Ranking Sektor (RRG)")
    if sector_ranking:
        lines.append("")
        lines.append("| Rank | Sektor | Kuadran | Skor | RS-Ratio | RS-Momentum |")
        lines.append("|------|--------|---------|------|----------|-------------|")
        for i, item in enumerate(sector_ranking, 1):
            sector = item[0]
            quadrant = item[1]
            score = item[2]
            rs_r = f"{item[3]:.1f}" if len(item) > 3 else "-"
            rs_m = f"{item[4]:.1f}" if len(item) > 4 else "-"
            lines.append(f"| {i} | {sector} | {quadrant} | {score} | {rs_r} | {rs_m} |")
    else:
        lines.append("Tidak ada data RRG tersedia.")
    lines.append("")

    lines.append("## 2. Kandidat Screening")
    if candidates:
        lines.append("")
        lines.append("| # | Kode | Nama | Sektor | Sinyal | WR Event | Potensi | DD |")
        lines.append("|---|------|------|--------|--------|----------|---------|-----|")
        for i, c in enumerate(candidates, 1):
            wr = f"{c.wr_event:.1f}%" if c.wr_event else "-"
            pot = f"+{c.potential:.0f}%" if c.potential else "-"
            dd = f"{c.drawdown:.0f}%" if c.drawdown else "-"
            lines.append(
                f"| {i} | {c.stock.code} | {c.stock.name} | "
                f"{c.stock.sector} | {c.bucket} | {wr} | {pot} | {dd} |"
            )
    else:
        lines.append("Tidak ada kandidat yang lolos filter hari ini.")
    lines.append("")

    lines.append("## 3. Validasi Mendalam")
    if validations:
        for v in validations:
            lines.append("")
            lines.append(format_validation_summary(v))
    else:
        lines.append("Tidak ada validasi (tidak ada kandidat).")
    lines.append("")

    lines.append("## 4. Kamus Metrik & Sumber Data")
    lines.append("")
    lines.append("Sesuai prinsip kejujuran data (PRD §8), berikut adalah definisi dan asal data dari setiap istilah:")
    lines.append("")
    lines.append("1. **Kategori Sinyal (Bucket)** — _Sumber: `idx-edge:screener_saham_terkini` (`screener_v5.py`)_")
    lines.append("   - **SINYAL BERSIH**: Konvergensi teknikal bullish (di atas MA5/MA20) + net buy asing signifikan + akumulasi top broker tanpa konflik distribusi.")
    lines.append("   - **SINYAL SENYAP**: Akumulasi pekat oleh broker utama atau asing saat volatilitas harga masih tenang (mode senyap / belum breakout).")
    lines.append("   - **AKUMULASI SENYAP**: Sinyal tier-2 dengan tanda akumulasi awal, disiapkan sebagai watchlist bila volume terkonfirmasi meningkat.")
    lines.append("   - **RISIKO PANTULAN / KONFLIK DISTRIBUSI**: Anomali di mana harga naik tetapi broker distribusi aktif atau asing melepas barang (diberi penalti skor/disaring).")
    lines.append("")
    lines.append("2. **Metrik Probabilitas Historis** — _Sumber: Model backtest event-based `idx-edge` (Jan 2020 - sekarang)_")
    lines.append("   - **WR Event (Win Rate Event)**: Probabilitas historis harga mencapai Target Profit (dinamis berbasis ATR) sebelum menyentuh Stop Loss dalam horizon D+2 s/d D+4.")
    lines.append("   - **Potensi**: Rata-rata persentase kenaikan harga maksimum historis pasca kemunculan pola sinyal serupa.")
    lines.append("   - **DD (Drawdown)**: Rata-rata penurunan harga terdalam (Maximum Adverse Excursion) selama periode holding.")
    lines.append("")
    lines.append("3. **Net Foreign Flow (Aliran Dana Asing Murni)** — _Sumber: `idx-edge:riwayat_harga` (`n_foreign`)_")
    lines.append("   - Menampilkan selisih lembar saham beli vs jual oleh investor tipe Asing (Foreign) murni, bukan estimasi formula tertutup.")
    lines.append("")
    lines.append("4. **Trade Plan & Pivot Levels** — _Sumber: Perhitungan lokal `src/pivot.py` dari OHLC harian_")
    lines.append("   - Cutloss divalidasi ketat selalu di bawah batas bawah Entry Range (S1/S2/buffer ATR).")
    lines.append("   - Target 1 & Target 2 diturunkan dari level resisten Pivot aktual (R1, R2, R3).")
    lines.append("")
    lines.append("5. **Fundamental & Valuasi** — _Sumber: `idx-edge:laporan_keuangan` & `analisa_saham`_")
    lines.append("   - Disarikan dari Laporan Keuangan resmi emiten: EPS, PER, DER, dan pertumbuhan pendapatan/laba YoY.")
    lines.append("")
    lines.append("---")
    lines.append("_Disclaimer: Analisa ini berbasis data historis dan pola statistik.")
    lines.append("Bukan ajakan jual/beli. Keputusan investasi tanggung jawab masing-masing._")

    return "\n".join(lines)


def save_report(content: str, output_dir: str) -> str:
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    date_str = datetime.now().strftime("%Y-%m-%d")
    filename = f"screener_{date_str}.md"
    filepath = out_path / filename
    filepath.write_text(content, encoding="utf-8")
    return str(filepath)
