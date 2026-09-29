"""
Screener IHSG - CLI Orchestrator

Run via the Antigravity agent:
  The agent reads this file, understands the pipeline,
  and executes MCP calls step by step.

Usage (for the agent):
  1. Call screener_saham_terkini (1 API call)
  2. For top 2-3 sectors from RRG, get riwayat_harga for benchmark + sector stocks
  3. Filter screener results by RRG-favored sectors
  4. For top 3-5 candidates, call analisa_saham + broker_summary + riwayat_harga
  5. Assemble validation and generate report
"""
import json
from datetime import datetime, timedelta
from pathlib import Path

from src.mcp_client import McpClient, load_sector_config, extract_closes
from src.models import (
    OHLCRow, Candidate, Stock, ValidationResult, RRGPoint, QuotaUsageBreakdown,
)
from src.sector_rrg import compute_rrg_for_stock, rank_sectors, select_representative_stocks
from src.screener import (
    parse_screener_rows, filter_by_sectors, filter_by_bucket, rank_candidates,
    screen_mandiri_constituents,
)
from src.validator import assemble_validation, build_validation_request_list
from src.report import generate_daily_report, save_report


PIPELINE_STEPS = """
STEP 1 - SCREENER (1 API call - hanya diperlukan untuk mode="upstream")
  Call: screener_saham_terkini (no params)
  Feed result rows into: parse_screener_rows()

STEP 2 - RRG for BENCHMARK (1 API call)
  Call: riwayat_harga(code="COMPOSITE", limit=120, frame="daily",
        fields="date,close")
  This is the IHSG composite benchmark.
  If "COMPOSITE" fails, use a proxy (e.g. BBCA proxy 60D).

STEP 3 - RRG & OHLC CACHE for SECTOR STOCKS (55 API calls)
  Untuk 11 sektor resmi IDX, ambil 5 saham representatif per sektor.
  PENTING: Tarik riwayat_harga dengan kolom lengkap:
    riwayat_harga(code=code, limit=60, frame="daily",
                  fields="date,open,high,low,close,volume,value,f_buy,f_sell,n_foreign")
  Biaya kuota tetap 1 API call per saham (total 55 call).
  Data ini berfungsi ganda:
  - Ekstrak closes untuk kalkulasi RRG Sektor (Leading/Improving/Weakening/Lagging).
  - Cache OHLC lengkap untuk penyaringan Mode Mandiri (PRD §6) tanpa kuota tambahan.

STEP 4 - FILTER CANDIDATES (DUAL MODE SCREENING)
  Mode "upstream" (Default):
    - Saring hasil screener_saham_terkini berdasarkan sektor Leading/Improving.
    - Saring berdasarkan bucket sinyal positif (SINYAL BERSIH, SINYAL SENYAP, AKUMULASI SENYAP).
  Mode "mandiri" (PRD §6 & §7.3):
    - Saring secara disiplin 4/4 kriteria wajib PRD §6:
      1. val >= Rp1 Miliar (val > 1mil)
      2. volume harian > MA20 volume (vol > ma20vol)
      3. Net Foreign Buy harian > 0 (n_foreign > 0 / f_buy > f_sell)
      4. close >= SMA20 close
    - Hasil: Lolos 4/4 kriteria -> "🟢 SINYAL MANDIRI (PRD §6)"

STEP 5 - VALIDATE TOP CANDIDATES (4 API calls per candidate)
  Untuk 3-5 kandidat teratas:
    - analisa_saham(code)           -> analysis_text (deteksi AVOID/skor/WR)
    - broker_summary(code)          -> broker_data (dengan catatan EOD jika kosong)
    - akumulasi_broker_historis(code) -> accumulation trend
    - laporan_keuangan(code)        -> deeper fundamentals
  Assemble validation dengan Trade Plan (aturan proteksi AVOID terintegrasi).

STEP 6 - GENERATE REPORT
  Gabungkan seluruh data ke Markdown report dengan badge mode screening yang jelas.
  Simpan ke output/ directory dan sinkronkan ke sdcard/Download.
"""


def create_pipeline_config() -> dict:
    """Generate the pipeline configuration for the agent to execute."""
    sector_config = load_sector_config()
    positive_buckets = ["SINYAL BERSIH", "SINYAL SENYAP", "AKUMULASI SENYAP"]
    max_sectors = 4
    max_candidates = 5
    output_dir = str(Path(__file__).parent.parent / "output")

    return {
        "sector_config": sector_config,
        "positive_buckets": positive_buckets,
        "max_sectors": max_sectors,
        "max_candidates": max_candidates,
        "output_dir": output_dir,
        "date": datetime.now().strftime("%Y-%m-%d"),
        "mode": "upstream",
    }


def run_pipeline(
    screener_data: dict,
    benchmark_ohlc: list[OHLCRow],
    sector_stock_closes: dict[str, dict[str, list[float]]],
    validations_data: dict[str, dict],
    output_dir: str | None = None,
    quota_used: int | QuotaUsageBreakdown = 0,
    date_str: str | None = None,
    mode: str = "upstream",
    stock_ohlc_map: dict[str, list[OHLCRow]] | None = None,
) -> str:
    """Execute the end-to-end screening and validation pipeline, returning saved report path."""
    config = create_pipeline_config()
    target_output_dir = output_dir or config["output_dir"]
    report_date = date_str or config["date"]

    # 1. Compute RRG for sectors vs benchmark
    # Official convention: benchmark_ohlc is ordered oldest-to-newest
    bench_closes = extract_closes(benchmark_ohlc)
    rep_stocks_map = select_representative_stocks(
        config["sector_config"], list(config["sector_config"].keys()), min_stocks=5
    )
    sector_points: dict[str, list[RRGPoint]] = {}
    for sector, stocks_data in sector_stock_closes.items():
        if sector == "Unknown" or sector not in config["sector_config"]:
            unmapped_codes = list(stocks_data.keys())
            print(f"Log: Menyaring sektor non-resmi '{sector}' ({len(unmapped_codes)} saham: {unmapped_codes}) dari tabel RRG.")
            continue
        rep_codes = set(rep_stocks_map.get(sector, []))
        has_configured_stocks = any(c in rep_codes for c in stocks_data.keys())
        points = []
        for code, closes in stocks_data.items():
            if has_configured_stocks and code not in rep_codes:
                print(f"Log: Menyaring saham non-sampel '{code}' dari perhitungan RRG sektor '{sector}' (mencegah kontaminasi kandidat).")
                continue
            if len(closes) >= 11 and len(bench_closes) >= 11:
                # Ensure equal length, matching the end of series
                min_len = min(len(closes), len(bench_closes))
                s_c = closes[-min_len:]
                b_c = bench_closes[-min_len:]
                pt = compute_rrg_for_stock(s_c, b_c, code)
                points.append(pt)
        sector_points[sector] = points

    sector_ranking = rank_sectors(sector_points)

    # Calculate actual stock sample count per sector for report transparency
    sector_counts = [len(pts) for pts in sector_points.values() if pts]
    if sector_counts and isinstance(quota_used, QuotaUsageBreakdown):
        min_c = min(sector_counts)
        max_c = max(sector_counts)
        sample_str = f"{min_c}" if min_c == max_c else f"{min_c}-{max_c}"
        if not isinstance(quota_used.details, dict):
            quota_used.details = {}
        quota_used.details["rrg_stocks_per_sector"] = sample_str
        if quota_used.rrg_sectors_processed == 0:
            quota_used.rrg_sectors_processed = len(sector_counts)
        if quota_used.rrg_stocks_processed == 0:
            quota_used.rrg_stocks_processed = sum(sector_counts)

    # 2. Determine candidates based on mode
    favored_sectors = [
        item[0] for item in sector_ranking if item[1] in ("Leading", "Improving")
    ]
    target_sectors = favored_sectors

    if mode == "mandiri":
        # Mode Mandiri: PRD §6 & §7.3 top-down screening from sector constituents
        if stock_ohlc_map is None:
            stock_ohlc_map = {}
            for code, vdata in validations_data.items():
                if "ohlc_rows" in vdata and vdata["ohlc_rows"]:
                    stock_ohlc_map[code] = vdata["ohlc_rows"]

        top_candidates = screen_mandiri_constituents(
            favored_sectors=target_sectors,
            sector_config=config["sector_config"],
            stock_ohlc_map=stock_ohlc_map,
            min_value=1_000_000_000.0,
            max_results=config["max_candidates"],
        )
    else:
        # Mode Upstream: uses screener_saham_terkini output from idx-edge
        raw_rows = screener_data.get("rows", [])
        all_candidates = parse_screener_rows(raw_rows, config["sector_config"])

        # Log unmapped candidate stocks
        unmapped_candidates = [c.stock.code for c in all_candidates if c.stock.sector == "Unknown"]
        if unmapped_candidates:
            print(f"Log: Terdeteksi {len(unmapped_candidates)} saham kandidat tidak terpetakan ke sektor resmi IDX: {unmapped_candidates}")

        if favored_sectors:
            sector_filtered = filter_by_sectors(all_candidates, favored_sectors)
        else:
            sector_filtered = []

        bucket_filtered = filter_by_bucket(sector_filtered, config["positive_buckets"])
        if not bucket_filtered and sector_filtered:
            bucket_filtered = sector_filtered

        top_candidates = rank_candidates(bucket_filtered, max_results=config["max_candidates"])

    # 3. Assemble validations
    validations: list[ValidationResult] = []
    for cand in top_candidates:
        c_code = cand.stock.code
        val_info = validations_data.get(c_code, {})
        has_analysis = bool(val_info.get("analysis_text"))
        
        fallback_msg = val_info.get("fallback_reason", "")
        if not has_analysis and not fallback_msg:
            fallback_msg = (
                f"Validasi mendalam dilewati untuk saham {c_code} guna efisiensi kuota API harian "
                f"(tier cadangan/sinyal sekunder). Lakukan cek manual bila diperlukan."
            )

        cand_ohlc = val_info.get("ohlc_rows") or (stock_ohlc_map.get(c_code, []) if stock_ohlc_map else [])

        val_res = assemble_validation(
            candidate=cand,
            analysis_text=val_info.get("analysis_text", ""),
            broker_data=val_info.get("broker_data", {}),
            ohlc_rows=cand_ohlc,
            fundamental_data=val_info.get("fundamental_data", {}),
            fallback_reason=fallback_msg,
        )
        validations.append(val_res)

    if isinstance(quota_used, QuotaUsageBreakdown):
        quota_used.validation_stocks_processed = len(validations)

    # 4. Generate report and save
    report_content = generate_daily_report(
        date=report_date,
        sector_ranking=sector_ranking,
        candidates=top_candidates,
        validations=validations,
        quota_used=quota_used,
        output_dir=target_output_dir,
        mode=mode,
    )

    saved_path = save_report(report_content, target_output_dir, date_str=report_date, mode=mode)
    return saved_path


if __name__ == "__main__":
    config = create_pipeline_config()
    print("Pipeline config loaded:")
    print(f"  Sectors: {len(config['sector_config'])}")
    print(f"  Date: {config['date']}")
    print(f"  Output: {config['output_dir']}")
    print()
    print("Steps for agent to execute:")
    print(PIPELINE_STEPS)
