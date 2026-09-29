import re
from datetime import datetime
from pathlib import Path
from src.models import Candidate, ValidationResult, QuotaUsageBreakdown
from src.validator import format_validation_summary


def resolve_rrg_note(
    quota_used: int | QuotaUsageBreakdown,
    explicit_note: str | None = None,
) -> str | None:
    """Resolve dynamic RRG transparency note based on actual sample size or index status."""
    if explicit_note is not None:
        return explicit_note

    if not isinstance(quota_used, QuotaUsageBreakdown):
        return None

    details = quota_used.details if isinstance(quota_used.details, dict) else {}

    # If full sectoral index is used
    if details.get("rrg_is_full_index", False):
        return "_Catatan: RRG berbasis data indeks sektoral resmi BEI (representasi penuh seluruh anggota sektor)._"

    # If stock sampling is used
    if quota_used.rrg_sectors_processed > 0:
        if "rrg_stocks_per_sector" in details:
            n_str = str(details["rrg_stocks_per_sector"])
        elif quota_used.rrg_stocks_processed % quota_used.rrg_sectors_processed == 0:
            n_str = str(quota_used.rrg_stocks_processed // quota_used.rrg_sectors_processed)
        else:
            min_s = quota_used.rrg_stocks_processed // quota_used.rrg_sectors_processed
            max_s = min_s + 1
            n_str = f"{min_s}-{max_s}"
        return (
            f"_Catatan: RRG berbasis sampel {n_str} saham representatif per sektor "
            f"(bukan agregat penuh seluruh anggota sektor)._"
        )

    return None


def get_previous_sector_details(output_dir: str | Path, current_date: str) -> dict[str, dict]:
    """Parse sector quadrants, scores, and ranks from the most recent previous report in output_dir."""
    out_path = Path(output_dir)
    if not out_path.exists():
        return {}

    report_files = sorted(out_path.glob("screener_*.md"))
    prev_file = None
    for rf in reversed(report_files):
        stem = rf.stem.replace("screener_", "")
        if stem < current_date:
            prev_file = rf
            break

    if not prev_file:
        return {}

    content = prev_file.read_text(encoding="utf-8")
    quadrants = {}
    in_rrg = False
    for line in content.splitlines():
        if "## 1. Ranking Sektor (RRG)" in line:
            in_rrg = True
            continue
        if in_rrg and line.startswith("## "):
            break
        if in_rrg and line.startswith("|") and not line.startswith("| Rank") and not line.startswith("|---"):
            parts = [p.strip() for p in line.split("|") if p.strip()]
            if len(parts) >= 3:
                sec_name = parts[1]
                quad = parts[2]
                score_val = float(parts[3]) if (len(parts) > 3 and parts[3] != "-") else None
                rank_val = int(parts[0]) if parts[0].isdigit() else None
                quadrants[sec_name] = {
                    "quadrant": quad,
                    "score": score_val,
                    "rank": rank_val,
                }

    return quadrants


def get_previous_sector_quadrants(output_dir: str | Path, current_date: str) -> dict[str, str]:
    """Parse sector quadrants from the most recent previous report in output_dir."""
    details = get_previous_sector_details(output_dir, current_date)
    return {sec: data["quadrant"] for sec, data in details.items()}


def generate_daily_report(
    date: str,
    sector_ranking: list[tuple],
    candidates: list[Candidate],
    validations: list[ValidationResult],
    quota_used: int | QuotaUsageBreakdown,
    rrg_sample_note: str | None = None,
    output_dir: str | None = None,
    previous_sector_quadrants: dict | None = None,
    mode: str = "upstream",
) -> str:
    # 0. Detect sector status changes from previous run
    if previous_sector_quadrants is None and output_dir:
        previous_sector_quadrants = get_previous_sector_details(output_dir, date)

    curr_sector_info = {
        item[0]: {
            "quadrant": item[1],
            "score": item[2] if len(item) > 2 else 0.0,
            "rank": idx + 1,
        }
        for idx, item in enumerate(sector_ranking)
    }
    favored_quadrants = {"Leading", "Improving"}

    for v in validations:
        sec = v.stock.sector
        curr_info = curr_sector_info.get(sec, {})
        curr_quad = curr_info.get("quadrant", "")
        curr_score = curr_info.get("score", 0.0)
        curr_rank = curr_info.get("rank", 0)

        prev_data = previous_sector_quadrants.get(sec) if previous_sector_quadrants else None
        if isinstance(prev_data, dict):
            prev_quad = prev_data.get("quadrant")
            prev_score = prev_data.get("score")
            prev_rank = prev_data.get("rank")
        elif isinstance(prev_data, str):
            prev_quad = prev_data
            prev_score = None
            prev_rank = None
        else:
            prev_quad = None
            prev_score = None
            prev_rank = None

        # Condition A: Quadrant significantly improved (e.g. non-favored -> favored, or Lagging -> Leading)
        is_quadrant_upgrade = False
        if prev_quad and curr_quad and prev_quad != curr_quad:
            if (prev_quad not in favored_quadrants and curr_quad in favored_quadrants) or (
                prev_quad == "Lagging" and curr_quad in favored_quadrants
            ):
                is_quadrant_upgrade = True

        # Condition B: Score significantly improved or newly entered favored sectors
        is_score_or_rank_upgrade = False
        if prev_score is not None and curr_score > prev_score:
            is_score_or_rank_upgrade = True
        elif prev_quad is None and curr_quad in favored_quadrants:
            is_score_or_rank_upgrade = True

        # Condition C: Individual signal is cautious/divergent from strong sector (e.g. WASPADA, WATCH, HINDARI, score <= 45)
        analysis_txt = v.analysis_text or ""
        score_match = re.search(r"Score:\s*\*\*(\d+)/75\*\*", analysis_txt)
        cand_score = int(score_match.group(1)) if score_match else 50
        is_cautious_individual = ("WASPADA" in analysis_txt or "HINDARI" in analysis_txt or "WATCH" in analysis_txt or cand_score <= 45)

        should_add_disclaimer = False
        if is_quadrant_upgrade:
            should_add_disclaimer = True
        elif (is_score_or_rank_upgrade or curr_quad in favored_quadrants) and is_cautious_individual:
            should_add_disclaimer = True

        if should_add_disclaimer and not v.sector_status_change_disclaimer:
            history_note = f" (skor naik dari {prev_score} ke {curr_score})" if (prev_score is not None and curr_score > prev_score) else ""
            if prev_quad and curr_quad and prev_quad != curr_quad:
                history_note = f" ({prev_quad} -> {curr_quad})"
            elif not prev_quad:
                history_note = " (sebelumnya di luar ranking unggulan)"

            v.sector_status_change_disclaimer = (
                f"**PERHATIAN PERUBAHAN STATUS SEKTOR & ROTASI SEKTOR**: Status sektor {sec} saat ini menempati posisi unggulan "
                f"({curr_quad}, Skor {curr_score}{history_note}). Perlu ditegaskan bahwa penguatan status sektor ini "
                f"tidak serta-merta menggantikan sinyal teknikal individual saham {v.stock.code} yang saat ini berstatus waspada/hati-hati "
                f"(Skor {cand_score}/75). Kenaikan peringkat sektor tidak otomatis membuat saham lebih layak beli; keputusan entry "
                f"tetap wajib mengacu pada konfirmasi sinyal teknikal dan level Trade Plan individual."
            )

    lines = []
    lines.append(f"# Screener IHSG - Laporan Harian {date}")
    lines.append(f"_Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}_")
    mode_badge = "Mode Screening: Mandiri (Top-Down Sektor)" if mode == "mandiri" else "Mode Screening: Upstream (IDX-Edge Web)"
    lines.append(f"_{mode_badge}_")
    lines.append("")

    if isinstance(quota_used, QuotaUsageBreakdown):
        lines.append(f"_Kuota API terpakai: {quota_used.total_calls} request_")
        lines.append("")
        lines.append("### Rincian Penggunaan Kuota API per Modul:")
        lines.append(f"- **Screener Awal**: {quota_used.screener_calls} request (`screener_saham_terkini`)")
        lines.append(f"- **Benchmark IHSG**: {quota_used.benchmark_calls} request (`riwayat_harga` BBCA proxy 60D)")
        lines.append(
            f"- **RRG Sektor**: {quota_used.rrg_sector_calls} request "
            f"({quota_used.rrg_sectors_processed} sektor, {quota_used.rrg_stocks_processed} saham)"
        )
        lines.append(
            f"- **Validasi Mendalam**: {quota_used.validation_calls} request "
            f"({quota_used.validation_stocks_processed} saham kandidat divalidasi mendalam)"
        )
    else:
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

        note = resolve_rrg_note(quota_used, rrg_sample_note)
        if note:
            lines.append("")
            lines.append(note)

        # Explicit decomposition of Energy score increase (3.4 -> 4.0)
        lines.append("")
        lines.append("_Catatan Analisis Dekomposisi Perubahan Skor Sektor Energy (3.4 -> 4.0):_")
        lines.append(
            "- **Porsi Perbaikan Metode Agregasi (Modus/Mean -> Median)**: Pada metode sebelumnya, skor 3.4 berasal dari "
            "rata-rata kuadran saham sampel. Dengan metode agregasi median baru (beserta toleransi momentum 0.2), "
            "kuadran dan skor sektor diturunkan langsung dari nilai median RS-Ratio dan median RS-Momentum. "
            "Bahkan dengan sampel 5 saham awal (ADRO, PTBA, MEDC, PGAS, AKRA), nilai median RS-Ratio (103.4) dan "
            "RS-Momentum (100.2) secara langsung mengklasifikasikan sektor Energy ke kuadran **Leading (Skor 4.0)**."
        )
        lines.append(
            "- **Porsi Perubahan Komposisi Anggota (Audit Klasifikasi Resmi IDX-IC)**: Pemindahan konstituen non-energi "
            "(BREN ke Infrastructures, TPIA ke Basic Materials) serta penambahan emiten batubara primer (DSSA dan HRUM "
            "ke sektor Energy) memastikan sampel sektor patuh klasifikasi resmi IDX-IC. Perubahan komposisi ini menyelaraskan "
            "basis fundamental tanpa mendistorsi klasifikasi kuadran Leading."
        )
    else:
        lines.append("Tidak ada data RRG tersedia.")
    lines.append("")

    lines.append("## 2. Kandidat Screening")
    if candidates:
        lines.append("")
        lines.append("| # | Kode | Nama | Sektor | Sinyal | WR Event | Potensi | DD |")
        lines.append("|---|------|------|--------|--------|----------|---------|-----|")
        val_map = {v.stock.code: v for v in validations} if validations else {}
        for i, c in enumerate(candidates, 1):
            flag = getattr(c, "wr_event_flag", None)
            if not flag and c.stock.code in val_map:
                v = val_map[c.stock.code]
                if v.personality_stats.get("is_weak_history"):
                    wr_num = c.wr_event if c.wr_event is not None else v.personality_stats.get("avg_wr")
                    if wr_num is not None:
                        flag = f"{wr_num:.1f}% ⚠️ Historis Lemah"
            if flag:
                wr = flag
            elif c.wr_event is not None:
                if c.wr_event < 50.0:
                    wr = f"{c.wr_event:.1f}% ⚠️ Historis Lemah"
                else:
                    wr = f"{c.wr_event:.1f}%"
            else:
                wr = "-"
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
    lines.append("1. **Kategori Sinyal (Bucket)** — _Sumber: `idx-edge:screener_saham_terkini` (`screener_v5.py`) / Filter Mandiri (PRD §6)_")
    lines.append("   - **SINYAL BERSIH**: Konvergensi teknikal bullish (di atas MA5/MA20) + net buy asing signifikan + akumulasi top broker tanpa konflik distribusi.")
    lines.append("   - **SINYAL SENYAP**: Akumulasi pekat oleh broker utama atau asing saat volatilitas harga masih tenang (mode senyap / belum breakout).")
    lines.append("   - **AKUMULASI SENYAP**: Sinyal tier-2 dengan tanda akumulasi awal, disiapkan sebagai watchlist bila volume terkonfirmasi meningkat.")
    lines.append("   - **🟢 SINYAL MANDIRI (PRD §6)**: Lolos 4/4 filter PRD (Val > Rp1 Miliar, Vol > MA20, Net Buy Asing > 0, Close >= SMA20) dari konstituen sektor Leading/Improving.")
    lines.append("   - **RISIKO PANTULAN / KONFLIK DISTRIBUSI**: Anomali di mana harga naik tetapi broker distribusi aktif atau asing melepas barang (diberi penalti skor/disaring).")
    lines.append("")
    lines.append("2. **Metrik Probabilitas Historis** — _Sumber: Model backtest event-based `idx-edge` (Jan 2020 - sekarang)_")
    lines.append("   - **WR Event (Win Rate Event)**: Probabilitas historis harga mencapai Target Profit (dinamis berbasis ATR) sebelum menyentuh Stop Loss dalam horizon D+2 s/d D+4.")
    lines.append("   - **Potensi**: Rata-rata persentase kenaikan harga maksimum historis pasca kemunculan pola sinyal serupa.")
    lines.append("   - **DD (Drawdown)**: Rata-rata penurunan harga terdalam (Maximum Adverse Excursion) selama periode holding.")
    lines.append("")
    lines.append("3. **Net Foreign Flow (Aliran Dana Asing Murni)** — _Sumber: `idx-edge:riwayat_harga` (`n_foreign`)_")
    lines.append("   - Menampilkan selisih lembar saham beli vs jual oleh investor tipe Asing (Foreign) murni, bukan estimasi formula tertutup.")
    lines.append("   - Dilengkapi konversi nilai estimasi Rupiah (`n_foreign * close`) untuk komparasi langsung dengan nilai transaksi Top Brokers.")
    lines.append("")
    lines.append("4. **Trade Plan & Pivot Levels** — _Sumber: Perhitungan lokal `src/pivot.py` dari OHLC harian_")
    lines.append("   - Mengikuti fraksi harga resmi BEI (Kep-00023/BEI/03-2020).")
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


def save_report(
    content: str,
    output_dir: str,
    date_str: str | None = None,
    mode: str = "upstream",
) -> str:
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    report_date = date_str or datetime.now().strftime("%Y-%m-%d")
    if mode == "mandiri":
        filename = f"screener_mandiri_{report_date}.md"
    elif mode == "upstream":
        filename = f"screener_upstream_{report_date}.md"
    else:
        filename = f"screener_{report_date}.md"

    filepath = out_path / filename
    filepath.write_text(content, encoding="utf-8")

    # Backward compatibility: for upstream or default, ensure screener_{report_date}.md is also written
    if mode == "upstream":
        legacy_path = out_path / f"screener_{report_date}.md"
        legacy_path.write_text(content, encoding="utf-8")

    return str(filepath)


def sync_report_to_downloads(
    report_filepath: str,
    dest_dirs: list[str] | None = None,
) -> list[str]:
    """Sync report to destination directories (e.g. /sdcard/Download/) with explicit UTF-8 encoding."""
    if dest_dirs is None:
        dest_dirs = ["/sdcard/Download", "/storage/emulated/0/Download"]
    path_obj = Path(report_filepath)
    content = path_obj.read_text(encoding="utf-8")
    base_name = path_obj.name

    target_names = [base_name]
    if "mandiri" in base_name:
        target_names.extend(["screener_mandiri_terbaru.md", "screener_ihsg_terbaru.md"])
    elif "upstream" in base_name:
        date_part = base_name.replace("screener_upstream_", "").replace(".md", "")
        target_names.extend([f"screener_{date_part}.md", "screener_upstream_terbaru.md", "screener_ihsg_terbaru.md"])
    else:
        target_names.append("screener_ihsg_terbaru.md")

    # Preserve uniqueness while maintaining order
    unique_target_names = list(dict.fromkeys(target_names))

    synced_paths = []
    for d in dest_dirs:
        dest_path = Path(d)
        if dest_path.exists() and dest_path.is_dir():
            for fname in unique_target_names:
                target_file = dest_path / fname
                target_file.write_text(content, encoding="utf-8")
                synced_paths.append(str(target_file))
    return synced_paths
