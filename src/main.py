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
from src.models import OHLCRow, Candidate, Stock
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
  Assemble validation with trade plan.

STEP 6 - GENERATE REPORT
  Combine all data into Markdown report.
  Save to output/ directory.

ESTIMATED QUOTA USAGE:
  Step 1:  1
  Step 2:  1
  Step 3:  ~20-50 (depending on sector count and batch usage)
  Step 5:  ~20 (4 calls x 5 candidates)
  Total:   ~42-72 requests (well within 1000/hr limit)
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


if __name__ == "__main__":
    config = create_pipeline_config()
    print("Pipeline config loaded:")
    print(f"  Sectors: {len(config['sector_config'])}")
    print(f"  Date: {config['date']}")
    print(f"  Output: {config['output_dir']}")
    print()
    print("Steps for agent to execute:")
    print(PIPELINE_STEPS)
