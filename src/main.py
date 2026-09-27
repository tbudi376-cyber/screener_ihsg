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

from src.mcp_client import McpClient, load_sector_config
from src.models import OHLCRow, Candidate, Stock, ValidationResult, RRGPoint
from src.sector_rrg import compute_rrg_for_stock, rank_sectors
from src.screener import parse_screener_rows, filter_by_sectors, filter_by_bucket, rank_candidates
from src.validator import assemble_validation, build_validation_request_list
from src.report import generate_daily_report, save_report


PIPELINE_STEPS = """
STEP 1 - SCREENER (1 API call)
  Call: screener_saham_terkini (no params)
  Feed result rows into: parse_screener_rows()

STEP 2 - RRG for BENCHMARK (1 API call)
  Call: riwayat_harga(code="COMPOSITE", limit=120, frame="daily",
        fields="date,close")
  This is the IHSG composite benchmark.
  If "COMPOSITE" fails, use a proxy (e.g. average of top 5 market cap stocks).

STEP 3 - RRG for SECTOR STOCKS (N API calls, use harga_batch to reduce)
  For each sector, pick 5-8 representative stocks.
  Call: harga_batch(codes="BBCA,BBRI,BMRI,...", fields="code,last_price")
  OR call riwayat_harga per stock for historical data.
  Compute RRG points, classify quadrants, rank sectors.

STEP 4 - FILTER CANDIDATES
  Intersect screener results with RRG-favored sectors (Leading/Improving).
  Filter by bucket (keep SINYAL BERSIH, SINYAL SENYAP, AKUMULASI SENYAP).
  Rank and take top 5.

STEP 5 - VALIDATE TOP CANDIDATES (4 API calls per candidate)
  For each candidate:
    - analisa_saham(code)           -> analysis_text
    - broker_summary(code)          -> broker_data
    - riwayat_harga(code, limit=60) -> ohlc_rows for ATR, pivot, foreign flow
    - akumulasi_broker_historis(code) -> accumulation trend
    - laporan_keuangan(code)        -> deeper fundamentals
  Assemble validation with trade plan.

STEP 6 - GENERATE REPORT
  Combine all data into Markdown report.
  Save to output/ directory.

ESTIMATED QUOTA USAGE:
  Step 1:  1
  Step 2:  1
  Step 3:  ~11-55 (depending on batch usage)
  Step 5:  ~35 (7 calls x 5 candidates)
  Total:   ~48-92 requests (well within 1000/hr limit)
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
    }


def run_pipeline(
    screener_data: dict,
    benchmark_ohlc: list[OHLCRow],
    sector_stock_closes: dict[str, dict[str, list[float]]],
    validations_data: dict[str, dict],
    output_dir: str | None = None,
    quota_used: int = 0,
    date_str: str | None = None,
) -> str:
    """Execute the end-to-end screening and validation pipeline, returning saved report path."""
    config = create_pipeline_config()
    target_output_dir = output_dir or config["output_dir"]
    report_date = date_str or config["date"]

    # 1. Parse screener rows into Candidate models
    raw_rows = screener_data.get("rows", [])
    all_candidates = parse_screener_rows(raw_rows, config["sector_config"])

    # 2. Compute RRG for sectors vs benchmark
    bench_closes = [r.close for r in reversed(benchmark_ohlc)]  # oldest to newest
    sector_points: dict[str, list[RRGPoint]] = {}
    for sector, stocks_data in sector_stock_closes.items():
        points = []
        for code, closes in stocks_data.items():
            if len(closes) >= 11 and len(bench_closes) >= 11:
                # Ensure equal length, matching the end of series
                min_len = min(len(closes), len(bench_closes))
                s_c = closes[-min_len:]
                b_c = bench_closes[-min_len:]
                pt = compute_rrg_for_stock(s_c, b_c, code)
                points.append(pt)
        sector_points[sector] = points

    sector_ranking = rank_sectors(sector_points)

    # 3. Filter candidates by favorable sectors (Leading / Improving)
    favored_sectors = [
        s for s, q, _ in sector_ranking if q in ("Leading", "Improving")
    ]
    if favored_sectors:
        sector_filtered = filter_by_sectors(all_candidates, favored_sectors)
    else:
        sector_filtered = all_candidates

    # 4. Filter by positive signal bucket
    bucket_filtered = filter_by_bucket(sector_filtered, config["positive_buckets"])
    if not bucket_filtered and sector_filtered:
        bucket_filtered = sector_filtered

    # 5. Rank top candidates
    top_candidates = rank_candidates(bucket_filtered, max_results=config["max_candidates"])

    # 6. Assemble validations
    validations: list[ValidationResult] = []
    for cand in top_candidates:
        c_code = cand.stock.code
        val_info = validations_data.get(c_code, {})
        val_res = assemble_validation(
            candidate=cand,
            analysis_text=val_info.get("analysis_text", "No detailed analysis available."),
            broker_data=val_info.get("broker_data", {}),
            ohlc_rows=val_info.get("ohlc_rows", []),
        )
        validations.append(val_res)

    # 7. Generate report and save
    report_content = generate_daily_report(
        date=report_date,
        sector_ranking=sector_ranking,
        candidates=top_candidates,
        validations=validations,
        quota_used=quota_used,
    )

    saved_path = save_report(report_content, target_output_dir)
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
