# Screener IHSG Otomatis Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Build a CLI-driven stock screening system for IHSG that pulls data from the `idx-edge` MCP server, filters candidates top-down by sector and RRG, validates with fundamental/technical/broker data, and outputs a structured daily report with trade plans.

**Architecture:** Python CLI application (no web server, no hosting). Each module is a standalone Python file under `src/`, orchestrated by a `main.py` runner. Data flows through a pipeline: Sector Mapping → RRG Calculation → Screening → Validation → Pivot → Report Generation. All API calls go through a thin MCP client wrapper that handles caching and quota tracking.

**Tech Stack:** Python 3.11+, no external dependencies beyond stdlib for v1 (math, json, csv, datetime, pathlib, dataclasses). MCP calls are made via `call_mcp_tool` at the Antigravity CLI level, so the scripts generate structured MCP call requests that the agent executes.

**Spec:** [PRD_screener_ihsg.md](file:///root/projects/screener_ihsg/PRD_screener_ihsg.md)

## Global Constraints

- Python 3.11+ stdlib only (no pip installs for v1)
- All MCP calls use server name `idx-edge`, parameter name `code` (not `kode`)
- Rate limit: **1000 requests per hour** (confirmed via instructions.md and `_meta.kuota_harian` in responses)
- `screener_saham_terkini` takes **zero parameters** (it returns all screener results, not filterable by sector at API level)
- `analisa_saham` returns pre-formatted text with scores, pivot, trade plan already computed server-side
- `analisa_batch` max 5 codes per call, `harga_batch` max 20 codes per call
- `riwayat_harga` fields include `f_buy`, `f_sell`, `n_foreign` (in shares, not Rupiah)
- `broker_summary` has `flow` param: `"F"` for foreign-only, `"D"` for domestic, `"all"` for both
- `done_details` has tick-level data: `time`, `price_num`, `qty_num`, `buyer`, `seller`, `buyer_type`, `seller_type`, `action` (SELL/BUY)
- `laporan_keuangan` `report_type="all"` costs 3 quota (one per report type)
- No "Money Flow" (MF) field exists in any API tool. The closest proxies: `n_foreign` from `riwayat_harga` (foreign net shares), `broker_summary` with `flow="F"` (foreign flow value), and `screener_saham_terkini` bucket/summary text (server-side scoring). Label honestly as "Net Foreign Flow", not "Money Flow".
- Sector-to-stock mapping is NOT available from any API endpoint. Must be maintained as a static config file, sourced from IDX sector classification.

## Resolved Open Questions (PRD §9)

| # | Question | Answer |
|---|---|---|
| 1 | Quota: 1000/hr or /day? | **Per hour.** `instructions.md` says "1000 request per jam". Response `_meta.kuota_harian` label says "harian" but the MCP docs say "jam". Treat as 1000/hr conservatively. |
| 2 | Money Flow field? | **No.** No MF field in `broker_summary`, `analisa_saham`, or any tool. Use "Net Foreign Flow" (`n_foreign` from `riwayat_harga`, or `broker_summary` flow="F"). |
| 3 | Sector→stock mapping? | **Manual.** No API endpoint for sector membership. Build static JSON config. |
| 4 | `done_details` format? | **Tick-level with timestamps.** Fields: `time` (HH:MM:SS), `price_num`, `qty_num`, `buyer`/`seller` (broker code), `buyer_type`/`seller_type` (F/D), `action` (BUY/SELL). Paginated (665K+ rows for BBCA daily). Sufficient for Fase 3 order flow analysis. |
| 5 | All 15 tools identified? | **Yes.** `screener_saham_terkini`, `analisa_saham`, `analisa_batch`, `broker_summary`, `akumulasi_broker_historis`, `riwayat_harga`, `laporan_keuangan`, `done_details`, `market_cap`, `cari_saham`, `seasonality_bulanan`, `status_server`, `transaksi_insider`, `harga_terkini`, `harga_batch`. |

---

## File Structure

```
screener_ihsg/
├── PRD_screener_ihsg.md              # spec (already present)
├── docs/superpowers/plans/           # this plan
├── config/
│   └── sectors.json                  # sector → stock code mapping (11 sectors)
├── src/
│   ├── __init__.py
│   ├── models.py                     # dataclasses: Stock, SectorScore, RRGPoint, Candidate, TradePlan, PivotLevels
│   ├── mcp_client.py                 # thin wrapper: call MCP tools, cache, quota tracking
│   ├── sector_rrg.py                 # RRG engine: RS-Ratio, RS-Momentum, quadrant classification
│   ├── screener.py                   # screening pipeline: filter by sector, liquidity, foreign flow
│   ├── validator.py                  # deep validation: fundamental + technical + broker + trade plan
│   ├── pivot.py                      # standard pivot calculation from OHLC
│   ├── report.py                     # output formatter: Markdown daily report
│   └── main.py                       # CLI orchestrator: run full pipeline
├── tests/
│   ├── __init__.py
│   ├── test_models.py
│   ├── test_pivot.py
│   ├── test_sector_rrg.py
│   ├── test_screener.py
│   ├── test_validator.py
│   └── test_report.py
└── output/                           # generated reports land here
```

---

### Task 1: Data Models and Pivot Calculator

**Files:**
- Create: `src/__init__.py`
- Create: `src/models.py`
- Create: `src/pivot.py`
- Create: `tests/__init__.py`
- Create: `tests/test_models.py`
- Create: `tests/test_pivot.py`

**Interfaces:**
- Consumes: nothing (standalone)
- Produces:
  - `PivotLevels` dataclass with fields: `pivot: float`, `r1: float`, `r2: float`, `r3: float`, `s1: float`, `s2: float`, `s3: float`
  - `Stock` dataclass: `code: str`, `name: str`, `sector: str`
  - `OHLCRow` dataclass: `date: str`, `open: float`, `high: float`, `low: float`, `close: float`, `volume: float`, `value: float`, `f_buy: float`, `f_sell: float`, `n_foreign: float`
  - `RRGPoint` dataclass: `code: str`, `rs_ratio: float`, `rs_momentum: float`, `quadrant: str`
  - `Candidate` dataclass: `stock: Stock`, `bucket: str`, `summary: str`, `wr_event: float | None`, `potential: float | None`, `drawdown: float | None`, `note: str`
  - `TradePlan` dataclass: `entry_low: float`, `entry_high: float`, `cutloss: float`, `target1: float`, `target2: float`, `rr_ratio: float`, `atr: float`
  - `ValidationResult` dataclass: `stock: Stock`, `analysis_text: str`, `broker_data: dict`, `foreign_flow_5d: list[float]`, `pivot: PivotLevels`, `trade_plan: TradePlan`
  - `calculate_pivot(high: float, low: float, close: float) -> PivotLevels`
  - `calculate_atr(ohlc_rows: list[OHLCRow], period: int = 14) -> float`
  - `calculate_trade_plan(close: float, atr: float, support: float) -> TradePlan` with asymmetric multipliers (CL: 1x ATR, TP1: 1.5x ATR, TP2: 2x ATR)

- [x] **Step 1: Write failing tests for PivotLevels**

```python
# tests/test_pivot.py
import unittest
from src.pivot import calculate_pivot, calculate_atr, calculate_trade_plan
from src.models import PivotLevels, OHLCRow, TradePlan


class TestPivot(unittest.TestCase):
    def test_standard_pivot_bbca(self):
        # BBCA 2026-09-25: H=6275 L=6200 C=6250
        result = calculate_pivot(high=6275, low=6200, close=6250)
        self.assertIsInstance(result, PivotLevels)
        self.assertAlmostEqual(result.pivot, (6275 + 6200 + 6250) / 3, places=2)
        self.assertAlmostEqual(result.r1, 2 * result.pivot - 6200, places=2)
        self.assertAlmostEqual(result.s1, 2 * result.pivot - 6275, places=2)
        self.assertAlmostEqual(result.r2, result.pivot + (6275 - 6200), places=2)
        self.assertAlmostEqual(result.s2, result.pivot - (6275 - 6200), places=2)

    def test_pivot_symmetry(self):
        result = calculate_pivot(high=100, low=90, close=95)
        self.assertGreater(result.r1, result.pivot)
        self.assertGreater(result.r2, result.r1)
        self.assertLess(result.s1, result.pivot)
        self.assertLess(result.s2, result.s1)

    def test_trade_plan_asymmetric_rr(self):
        # CL = 1x ATR below close, TP1 = 1.5x ATR above close
        plan = calculate_trade_plan(close=6250, atr=136, support=6200)
        self.assertIsInstance(plan, TradePlan)
        self.assertAlmostEqual(plan.cutloss, 6250 - 136, places=0)
        self.assertAlmostEqual(plan.target1, 6250 + 1.5 * 136, places=0)
        self.assertAlmostEqual(plan.target2, 6250 + 2.0 * 136, places=0)
        self.assertGreater(plan.rr_ratio, 1.0,
                           "R:R must be > 1.0 to avoid the old SmartScreener bug")

    def test_atr_calculation(self):
        rows = [
            OHLCRow(date=f"2026-09-{25-i:02d}", open=6200+i*10,
                    high=6275+i*5, low=6200-i*5, close=6250+i*3,
                    volume=89e6, value=558e9, f_buy=0, f_sell=0, n_foreign=0)
            for i in range(15)
        ]
        atr = calculate_atr(rows, period=14)
        self.assertGreater(atr, 0)
        self.assertIsInstance(atr, float)


if __name__ == "__main__":
    unittest.main()
```

- [x] **Step 2: Run tests to verify they fail**

Run: `cd /root/projects/screener_ihsg && python -m pytest tests/test_pivot.py -v`
Expected: FAIL with "ModuleNotFoundError: No module named 'src'"

- [x] **Step 3: Create models.py with all dataclasses**

```python
# src/models.py
from dataclasses import dataclass, field


@dataclass
class Stock:
    code: str
    name: str
    sector: str


@dataclass
class OHLCRow:
    date: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    value: float
    f_buy: float = 0.0
    f_sell: float = 0.0
    n_foreign: float = 0.0


@dataclass
class PivotLevels:
    pivot: float
    r1: float
    r2: float
    r3: float
    s1: float
    s2: float
    s3: float


@dataclass
class RRGPoint:
    code: str
    rs_ratio: float
    rs_momentum: float
    quadrant: str  # "Leading", "Improving", "Weakening", "Lagging"


@dataclass
class TradePlan:
    entry_low: float
    entry_high: float
    cutloss: float
    target1: float
    target2: float
    rr_ratio: float
    atr: float


@dataclass
class Candidate:
    stock: Stock
    bucket: str
    summary: str
    wr_event: float | None = None
    potential: float | None = None
    drawdown: float | None = None
    note: str = ""


@dataclass
class ValidationResult:
    stock: Stock
    analysis_text: str
    broker_data: dict = field(default_factory=dict)
    foreign_flow_5d: list = field(default_factory=list)
    pivot: PivotLevels | None = None
    trade_plan: TradePlan | None = None
```

- [x] **Step 4: Create pivot.py with calculation functions**

```python
# src/pivot.py
from src.models import PivotLevels, OHLCRow, TradePlan


def calculate_pivot(high: float, low: float, close: float) -> PivotLevels:
    pivot = (high + low + close) / 3
    r1 = 2 * pivot - low
    s1 = 2 * pivot - high
    r2 = pivot + (high - low)
    s2 = pivot - (high - low)
    r3 = high + 2 * (pivot - low)
    s3 = low - 2 * (high - pivot)
    return PivotLevels(
        pivot=round(pivot, 2),
        r1=round(r1, 2),
        r2=round(r2, 2),
        r3=round(r3, 2),
        s1=round(s1, 2),
        s2=round(s2, 2),
        s3=round(s3, 2),
    )


def calculate_atr(ohlc_rows: list[OHLCRow], period: int = 14) -> float:
    if len(ohlc_rows) < 2:
        raise ValueError(f"Need at least 2 rows for ATR, got {len(ohlc_rows)}")

    true_ranges = []
    for i in range(len(ohlc_rows) - 1):
        current = ohlc_rows[i]
        prev = ohlc_rows[i + 1]  # rows are newest-first from API
        tr = max(
            current.high - current.low,
            abs(current.high - prev.close),
            abs(current.low - prev.close),
        )
        true_ranges.append(tr)

    use = true_ranges[:period]
    if not use:
        raise ValueError("Not enough data to calculate ATR")
    return sum(use) / len(use)


def calculate_trade_plan(close: float, atr: float, support: float) -> TradePlan:
    cutloss = close - 1.0 * atr
    target1 = close + 1.5 * atr
    target2 = close + 2.0 * atr
    entry_low = support
    entry_high = close
    risk = close - cutloss
    reward = target1 - close
    rr_ratio = round(reward / risk, 2) if risk > 0 else 0.0
    return TradePlan(
        entry_low=round(entry_low, 0),
        entry_high=round(entry_high, 0),
        cutloss=round(cutloss, 0),
        target1=round(target1, 0),
        target2=round(target2, 0),
        rr_ratio=rr_ratio,
        atr=round(atr, 2),
    )
```

- [x] **Step 5: Create `src/__init__.py` and `tests/__init__.py`**

```python
# src/__init__.py
# (empty)
```

```python
# tests/__init__.py
# (empty)
```

- [x] **Step 6: Run tests to verify they pass**

Run: `cd /root/projects/screener_ihsg && python -m pytest tests/test_pivot.py -v`
Expected: 4 tests PASS

- [x] **Step 7: Commit**

```bash
cd /root/projects/screener_ihsg
git init
git add src/__init__.py src/models.py src/pivot.py tests/__init__.py tests/test_pivot.py
git commit -m "feat: add data models and pivot calculator with asymmetric R:R trade plan"
```

---

### Task 2: Sector Config and MCP Client Wrapper

**Files:**
- Create: `config/sectors.json`
- Create: `src/mcp_client.py`
- Create: `tests/test_models.py`

**Interfaces:**
- Consumes: `models.OHLCRow`, `models.Stock` (from Task 1)
- Produces:
  - `config/sectors.json`: `dict[str, list[str]]` mapping sector name → list of stock codes
  - `load_sector_config() -> dict[str, list[str]]`
  - `get_stocks_for_sector(sector: str) -> list[str]`
  - `McpClient` class with methods:
    - `get_screener() -> list[dict]`
    - `get_price_history(code: str, limit: int, frame: str) -> list[OHLCRow]`
    - `get_broker_summary(code: str, flow: str) -> dict`
    - `get_accumulation(code: str, start_date: str, end_date: str) -> dict`
    - `get_analysis(code: str) -> str`
    - `get_analysis_batch(codes: list[str]) -> list[dict]`
    - `get_financial_report(code: str, report_type: str) -> dict`
    - `get_price_batch(codes: list[str]) -> list[dict]`
    - `quota_remaining() -> int`

- [x] **Step 1: Write test for sector config loading**

```python
# tests/test_models.py
import unittest
import json
from pathlib import Path


class TestSectorConfig(unittest.TestCase):
    def test_sectors_json_exists(self):
        path = Path(__file__).parent.parent / "config" / "sectors.json"
        self.assertTrue(path.exists(), f"Missing {path}")

    def test_sectors_has_11_sectors(self):
        path = Path(__file__).parent.parent / "config" / "sectors.json"
        with open(path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 11)

    def test_each_sector_has_stocks(self):
        path = Path(__file__).parent.parent / "config" / "sectors.json"
        with open(path) as f:
            data = json.load(f)
        for sector, stocks in data.items():
            self.assertIsInstance(stocks, list, f"{sector} stocks must be a list")
            self.assertGreater(len(stocks), 0, f"{sector} has no stocks")
            for code in stocks:
                self.assertRegex(code, r'^[A-Z0-9]{4}$', f"Invalid code: {code}")

    def test_known_sectors_present(self):
        path = Path(__file__).parent.parent / "config" / "sectors.json"
        with open(path) as f:
            data = json.load(f)
        expected = [
            "Energy", "Basic Materials", "Industrials",
            "Consumer Non-Cyclicals", "Consumer Cyclicals",
            "Healthcare", "Financials", "Properties & Real Estate",
            "Technology", "Infrastructures", "Transportation & Logistic",
        ]
        for s in expected:
            self.assertIn(s, data, f"Missing sector: {s}")


if __name__ == "__main__":
    unittest.main()
```

- [x] **Step 2: Run test to verify it fails**

Run: `cd /root/projects/screener_ihsg && python -m pytest tests/test_models.py -v`
Expected: FAIL with "AssertionError: Missing config/sectors.json"

- [x] **Step 3: Create sectors.json**

Create `config/sectors.json` with the 11 IDX JASICA sector classifications. Use the top liquid stocks per sector (minimum 10 per sector, up to 30 for large sectors like Financials). Source: IDX sector classification as of September 2026.

The exact stock lists must be populated by querying the API or from IDX public data. For the initial version, include the well-known liquid stocks:

```json
{
  "Energy": ["ADRO", "PTBA", "MEDC", "PGAS", "AKRA", "ELSA", "RAJA", "ESSA", "BREN", "TPIA"],
  "Basic Materials": ["INKP", "TKIM", "INTP", "SMGR", "BRPT", "MDKA", "ANTM", "INCO", "ADMR", "UNVR"],
  "Industrials": ["ASII", "UNTR", "SMDR", "IMPC", "ARNA", "SGER", "MASA", "BRMS", "AUTO", "GJTL"],
  "Consumer Non-Cyclicals": ["ICBP", "INDF", "CPIN", "HMSP", "GGRM", "KLBF", "JPFA", "MYOR", "SIDO", "ULTJ"],
  "Consumer Cyclicals": ["ERAA", "ACES", "MAPI", "LPPF", "RALS", "MSIN", "PGEO", "EMTK", "MTDL", "DSSA"],
  "Healthcare": ["HEAL", "SILO", "MIKA", "PRDA", "DVLA", "TSPC", "PYFA", "SOHO", "KLBF", "SIDO"],
  "Financials": ["BBCA", "BBRI", "BMRI", "BBNI", "BRIS", "BBTN", "PNBN", "NISP", "BTPS", "BNGA", "ARTO", "BJTM", "MEGA", "BDMN", "BBYB"],
  "Properties & Real Estate": ["BSDE", "CTRA", "SMRA", "PWON", "LPKR", "DILD", "APLN", "JRPT", "PPRO", "MKPI"],
  "Technology": ["GOTO", "BUKA", "DCII", "CASH", "EDGE", "MTDL", "LUCK", "TECH", "DMMX", "NELY"],
  "Infrastructures": ["TLKM", "TOWR", "TBIG", "JSMR", "WIKA", "WSKT", "PTPP", "ACST", "ISAT", "EXCL"],
  "Transportation & Logistic": ["GIAA", "BIRD", "SMDR", "TMAS", "ASSA", "JAYA", "BLTA", "SAFE", "HELI", "SAPX"]
}
```

> **Note for executor:** This is a starter mapping. Verify and update codes by running `cari_saham` for any unfamiliar codes. Remove duplicates across sectors (KLBF, SIDO appear in both Consumer Non-Cyclicals and Healthcare; SMDR in Industrials and Transportation; MTDL in Consumer Cyclicals and Technology). Keep each code in its primary IDX sector only.

- [x] **Step 4: Create mcp_client.py**

```python
# src/mcp_client.py
import json
from dataclasses import dataclass
from pathlib import Path
from src.models import OHLCRow


@dataclass
class McpCallRequest:
    """Represents a call to be made via the MCP idx-edge server.
    The agent executor translates these into actual call_mcp_tool invocations."""
    tool_name: str
    arguments: dict


class McpClient:
    """Wrapper for idx-edge MCP tool calls.

    In v1, this class produces McpCallRequest objects that the orchestrating
    agent executes. It tracks quota usage and caches results within a session.
    """

    def __init__(self):
        self._cache: dict[str, any] = {}
        self._quota_used = 0

    def quota_used(self) -> int:
        return self._quota_used

    def _cache_key(self, tool: str, **kwargs) -> str:
        return f"{tool}:{json.dumps(kwargs, sort_keys=True)}"

    def _record_call(self, quota_cost: int = 1):
        self._quota_used += quota_cost

    def get_screener_request(self) -> McpCallRequest:
        return McpCallRequest(
            tool_name="screener_saham_terkini",
            arguments={},
        )

    def get_price_history_request(
        self, code: str, limit: int = 120, frame: str = "daily",
        fields: str | None = None,
    ) -> McpCallRequest:
        args = {"code": code, "limit": limit, "frame": frame}
        if fields:
            args["fields"] = fields
        return McpCallRequest(tool_name="riwayat_harga", arguments=args)

    def get_broker_summary_request(
        self, code: str, flow: str = "all", broker_limit: int = 10,
    ) -> McpCallRequest:
        return McpCallRequest(
            tool_name="broker_summary",
            arguments={"code": code, "flow": flow, "broker_limit": broker_limit},
        )

    def get_accumulation_request(
        self, code: str, start_date: str | None = None, end_date: str | None = None,
        top: int = 3,
    ) -> McpCallRequest:
        args = {"code": code, "top": top}
        if start_date:
            args["start_date"] = start_date
        if end_date:
            args["end_date"] = end_date
        return McpCallRequest(tool_name="akumulasi_broker_historis", arguments=args)

    def get_analysis_request(self, code: str) -> McpCallRequest:
        return McpCallRequest(tool_name="analisa_saham", arguments={"code": code})

    def get_analysis_batch_request(self, codes: list[str]) -> McpCallRequest:
        return McpCallRequest(
            tool_name="analisa_batch",
            arguments={"codes": ",".join(codes[:5])},
        )

    def get_financial_report_request(
        self, code: str, report_type: str = "all", period: str = "quarterly",
        limit: int = 4,
    ) -> McpCallRequest:
        return McpCallRequest(
            tool_name="laporan_keuangan",
            arguments={
                "code": code, "report_type": report_type,
                "period": period, "limit": limit,
            },
        )

    def get_price_batch_request(self, codes: list[str]) -> McpCallRequest:
        return McpCallRequest(
            tool_name="harga_batch",
            arguments={"codes": ",".join(codes[:20])},
        )

    @staticmethod
    def parse_ohlc_rows(api_rows: list[dict]) -> list[OHLCRow]:
        return [
            OHLCRow(
                date=r.get("date", ""),
                open=float(r.get("open", 0)),
                high=float(r.get("high", 0)),
                low=float(r.get("low", 0)),
                close=float(r.get("close", 0)),
                volume=float(r.get("volume", 0)),
                value=float(r.get("value", 0)),
                f_buy=float(r.get("f_buy", 0)),
                f_sell=float(r.get("f_sell", 0)),
                n_foreign=float(r.get("n_foreign", 0)),
            )
            for r in api_rows
        ]


def load_sector_config() -> dict[str, list[str]]:
    path = Path(__file__).parent.parent / "config" / "sectors.json"
    with open(path) as f:
        return json.load(f)


def get_stocks_for_sector(sector: str) -> list[str]:
    config = load_sector_config()
    return config.get(sector, [])
```

- [x] **Step 5: Run all tests**

Run: `cd /root/projects/screener_ihsg && python -m pytest tests/ -v`
Expected: All tests PASS (test_models + test_pivot)

- [x] **Step 6: Commit**

```bash
cd /root/projects/screener_ihsg
git add config/sectors.json src/mcp_client.py tests/test_models.py
git commit -m "feat: add sector config (11 sectors) and MCP client wrapper"
```

---

### Task 3: RRG Engine (Relative Rotation Graph)

**Files:**
- Create: `src/sector_rrg.py`
- Create: `tests/test_sector_rrg.py`

**Interfaces:**
- Consumes:
  - `models.OHLCRow` (from Task 1)
  - `models.RRGPoint` (from Task 1)
  - `mcp_client.load_sector_config()` (from Task 2)
- Produces:
  - `calculate_rs_ratio(stock_prices: list[float], benchmark_prices: list[float], period: int = 10) -> list[float]`
  - `calculate_rs_momentum(rs_ratios: list[float], period: int = 10) -> list[float]`
  - `classify_quadrant(rs_ratio: float, rs_momentum: float) -> str` returns "Leading" | "Improving" | "Weakening" | "Lagging"
  - `rank_sectors(sector_rrg_points: dict[str, list[RRGPoint]]) -> list[tuple[str, str]]` returns `[(sector_name, dominant_quadrant), ...]` sorted by attractiveness

- [x] **Step 1: Write failing tests for RRG calculations**

```python
# tests/test_sector_rrg.py
import unittest
from src.sector_rrg import (
    calculate_rs_ratio,
    calculate_rs_momentum,
    classify_quadrant,
    normalize_to_100,
)


class TestRRG(unittest.TestCase):
    def test_rs_ratio_outperformer(self):
        # stock goes up, benchmark flat
        stock = [100 + i * 2 for i in range(30)]
        bench = [100 + i * 0.5 for i in range(30)]
        ratios = calculate_rs_ratio(stock, bench, period=10)
        self.assertGreater(len(ratios), 0)
        self.assertGreater(ratios[-1], ratios[0],
                           "RS-Ratio should increase when stock outperforms")

    def test_rs_ratio_underperformer(self):
        stock = [100 - i * 1 for i in range(30)]
        bench = [100 + i * 1 for i in range(30)]
        ratios = calculate_rs_ratio(stock, bench, period=10)
        self.assertLess(ratios[-1], ratios[0])

    def test_rs_momentum_rising(self):
        ratios = [100 + i * 0.5 for i in range(30)]
        momentum = calculate_rs_momentum(ratios, period=10)
        self.assertGreater(len(momentum), 0)
        self.assertGreater(momentum[-1], 100,
                           "Momentum should be >100 when ratio is rising")

    def test_classify_quadrant_leading(self):
        self.assertEqual(classify_quadrant(105, 102), "Leading")

    def test_classify_quadrant_improving(self):
        self.assertEqual(classify_quadrant(95, 102), "Improving")

    def test_classify_quadrant_weakening(self):
        self.assertEqual(classify_quadrant(105, 98), "Weakening")

    def test_classify_quadrant_lagging(self):
        self.assertEqual(classify_quadrant(95, 98), "Lagging")

    def test_normalize_centers_at_100(self):
        values = [90, 95, 100, 105, 110]
        normed = normalize_to_100(values)
        self.assertAlmostEqual(sum(normed) / len(normed), 100, places=0)


if __name__ == "__main__":
    unittest.main()
```

- [x] **Step 2: Run test to verify it fails**

Run: `cd /root/projects/screener_ihsg && python -m pytest tests/test_sector_rrg.py -v`
Expected: FAIL with "ModuleNotFoundError"

- [x] **Step 3: Implement RRG engine**

```python
# src/sector_rrg.py
from src.models import RRGPoint


def normalize_to_100(values: list[float]) -> list[float]:
    if not values:
        return []
    mean = sum(values) / len(values)
    if mean == 0:
        return [100.0] * len(values)
    return [v / mean * 100 for v in values]


def calculate_rs_ratio(
    stock_prices: list[float],
    benchmark_prices: list[float],
    period: int = 10,
) -> list[float]:
    """JdK RS-Ratio: relative strength of stock vs benchmark, smoothed.

    Both price lists must be same length, ordered oldest-to-newest.
    Returns normalized RS-Ratio series centered around 100.
    """
    if len(stock_prices) != len(benchmark_prices):
        raise ValueError("Price series must be same length")
    if len(stock_prices) < period + 1:
        raise ValueError(f"Need at least {period + 1} data points")

    raw_rs = [s / b * 100 if b != 0 else 100 for s, b in zip(stock_prices, benchmark_prices)]

    smoothed = _ema(raw_rs, period)

    return normalize_to_100(smoothed)


def calculate_rs_momentum(
    rs_ratios: list[float],
    period: int = 10,
) -> list[float]:
    """JdK RS-Momentum: rate of change of RS-Ratio, smoothed.

    Returns normalized momentum series centered around 100.
    Values > 100 = RS-Ratio is rising (improving), < 100 = falling.
    """
    if len(rs_ratios) < period + 1:
        raise ValueError(f"Need at least {period + 1} RS-Ratio values")

    roc = []
    for i in range(1, len(rs_ratios)):
        if rs_ratios[i - 1] != 0:
            roc.append(rs_ratios[i] / rs_ratios[i - 1] * 100)
        else:
            roc.append(100)

    smoothed = _ema(roc, period)
    return normalize_to_100(smoothed)


def _ema(data: list[float], period: int) -> list[float]:
    if len(data) < period:
        return data[:]
    k = 2 / (period + 1)
    result = [sum(data[:period]) / period]
    for i in range(period, len(data)):
        result.append(data[i] * k + result[-1] * (1 - k))
    return result


def classify_quadrant(rs_ratio: float, rs_momentum: float) -> str:
    if rs_ratio >= 100 and rs_momentum >= 100:
        return "Leading"
    if rs_ratio < 100 and rs_momentum >= 100:
        return "Improving"
    if rs_ratio >= 100 and rs_momentum < 100:
        return "Weakening"
    return "Lagging"


def compute_rrg_for_stock(
    stock_closes: list[float],
    benchmark_closes: list[float],
    code: str,
    period: int = 10,
) -> RRGPoint:
    rs_ratios = calculate_rs_ratio(stock_closes, benchmark_closes, period)
    rs_momentum = calculate_rs_momentum(rs_ratios, period)
    latest_ratio = rs_ratios[-1] if rs_ratios else 100
    latest_momentum = rs_momentum[-1] if rs_momentum else 100
    quadrant = classify_quadrant(latest_ratio, latest_momentum)
    return RRGPoint(
        code=code,
        rs_ratio=round(latest_ratio, 2),
        rs_momentum=round(latest_momentum, 2),
        quadrant=quadrant,
    )


def rank_sectors(
    sector_points: dict[str, list[RRGPoint]],
) -> list[tuple[str, str, float]]:
    """Rank sectors by attractiveness.

    Returns [(sector_name, dominant_quadrant, score), ...] sorted by score DESC.
    Leading=4, Improving=3, Weakening=2, Lagging=1.
    Score = weighted average of stock quadrants in that sector.
    """
    quadrant_score = {"Leading": 4, "Improving": 3, "Weakening": 2, "Lagging": 1}
    results = []
    for sector, points in sector_points.items():
        if not points:
            continue
        scores = [quadrant_score[p.quadrant] for p in points]
        avg = sum(scores) / len(scores)
        dominant = max(set(p.quadrant for p in points),
                       key=lambda q: sum(1 for p in points if p.quadrant == q))
        results.append((sector, dominant, round(avg, 2)))
    results.sort(key=lambda x: x[2], reverse=True)
    return results
```

- [x] **Step 4: Run tests to verify they pass**

Run: `cd /root/projects/screener_ihsg && python -m pytest tests/test_sector_rrg.py -v`
Expected: All 8 tests PASS

- [x] **Step 5: Commit**

```bash
cd /root/projects/screener_ihsg
git add src/sector_rrg.py tests/test_sector_rrg.py
git commit -m "feat: add RRG engine with RS-Ratio, RS-Momentum, and sector ranking"
```

---

### Task 4: Screening Pipeline

**Files:**
- Create: `src/screener.py`
- Create: `tests/test_screener.py`

**Interfaces:**
- Consumes:
  - `mcp_client.load_sector_config()` (from Task 2)
  - `models.Candidate`, `models.Stock` (from Task 1)
  - `sector_rrg.rank_sectors()` (from Task 3)
- Produces:
  - `parse_screener_rows(api_rows: list[dict], sector_config: dict) -> list[Candidate]`
  - `filter_by_sectors(candidates: list[Candidate], allowed_sectors: list[str]) -> list[Candidate]`
  - `filter_by_bucket(candidates: list[Candidate], allowed_buckets: list[str]) -> list[Candidate]`
  - `rank_candidates(candidates: list[Candidate], max_results: int = 5) -> list[Candidate]`

- [x] **Step 1: Write failing tests for screening pipeline**

```python
# tests/test_screener.py
import unittest
from src.screener import (
    parse_screener_rows,
    filter_by_sectors,
    filter_by_bucket,
    rank_candidates,
)
from src.models import Candidate, Stock


class TestScreener(unittest.TestCase):
    def setUp(self):
        self.sector_config = {
            "Financials": ["BBCA", "BBRI", "BMRI"],
            "Energy": ["ADRO", "PTBA", "MEDC"],
            "Technology": ["GOTO", "BUKA"],
        }
        self.sample_rows = [
            {
                "stock_code": "BBCA",
                "stock_name": "Bank Central Asia Tbk.",
                "bucket": "SINYAL BERSIH",
                "summary": "asing beli kuat",
                "wr_event": 74.1,
                "potential": 11.0,
                "drawdown": -5.0,
                "note": "",
            },
            {
                "stock_code": "ADRO",
                "stock_name": "Adaro Energy Tbk.",
                "bucket": "SINYAL SENYAP",
                "summary": "top broker akumulasi",
                "wr_event": 66.7,
                "potential": 8.0,
                "drawdown": -3.0,
                "note": "teknikal lemah",
            },
            {
                "stock_code": "GOTO",
                "stock_name": "GoTo Gojek Tokopedia Tbk.",
                "bucket": "RISIKO PANTULAN",
                "summary": "broker jual",
                "wr_event": 40.0,
                "potential": 5.0,
                "drawdown": -8.0,
                "note": "risiko pantulan",
            },
        ]

    def test_parse_screener_rows(self):
        candidates = parse_screener_rows(self.sample_rows, self.sector_config)
        self.assertEqual(len(candidates), 3)
        self.assertEqual(candidates[0].stock.code, "BBCA")
        self.assertEqual(candidates[0].stock.sector, "Financials")

    def test_parse_assigns_sector_from_config(self):
        candidates = parse_screener_rows(self.sample_rows, self.sector_config)
        self.assertEqual(candidates[1].stock.sector, "Energy")
        self.assertEqual(candidates[2].stock.sector, "Technology")

    def test_filter_by_sectors(self):
        candidates = parse_screener_rows(self.sample_rows, self.sector_config)
        filtered = filter_by_sectors(candidates, ["Financials", "Energy"])
        codes = [c.stock.code for c in filtered]
        self.assertIn("BBCA", codes)
        self.assertIn("ADRO", codes)
        self.assertNotIn("GOTO", codes)

    def test_filter_by_bucket_positive(self):
        candidates = parse_screener_rows(self.sample_rows, self.sector_config)
        filtered = filter_by_bucket(candidates, ["SINYAL BERSIH", "SINYAL SENYAP"])
        self.assertEqual(len(filtered), 2)

    def test_rank_limits_results(self):
        candidates = parse_screener_rows(self.sample_rows, self.sector_config)
        ranked = rank_candidates(candidates, max_results=2)
        self.assertEqual(len(ranked), 2)

    def test_rank_prefers_higher_wr_event(self):
        candidates = parse_screener_rows(self.sample_rows, self.sector_config)
        ranked = rank_candidates(candidates, max_results=3)
        self.assertEqual(ranked[0].stock.code, "BBCA")

    def test_empty_screener_rows(self):
        candidates = parse_screener_rows([], self.sector_config)
        self.assertEqual(candidates, [])
        msg_candidates = rank_candidates(candidates)
        self.assertEqual(msg_candidates, [])


if __name__ == "__main__":
    unittest.main()
```

- [x] **Step 2: Run test to verify it fails**

Run: `cd /root/projects/screener_ihsg && python -m pytest tests/test_screener.py -v`
Expected: FAIL with "ModuleNotFoundError"

- [x] **Step 3: Implement screening pipeline**

```python
# src/screener.py
import re
from src.models import Candidate, Stock


def _find_sector(code: str, sector_config: dict[str, list[str]]) -> str:
    for sector, codes in sector_config.items():
        if code in codes:
            return sector
    return "Unknown"


def _clean_bucket(raw_bucket: str) -> str:
    return re.sub(r'[^\w\s]', '', raw_bucket).strip()


def parse_screener_rows(
    api_rows: list[dict],
    sector_config: dict[str, list[str]],
) -> list[Candidate]:
    candidates = []
    for row in api_rows:
        code = row.get("stock_code", "")
        if not code:
            continue
        sector = _find_sector(code, sector_config)
        stock = Stock(
            code=code,
            name=row.get("stock_name", ""),
            sector=sector,
        )
        candidates.append(Candidate(
            stock=stock,
            bucket=_clean_bucket(row.get("bucket", "")),
            summary=row.get("summary", ""),
            wr_event=row.get("wr_event"),
            potential=row.get("potential"),
            drawdown=row.get("drawdown"),
            note=row.get("note", ""),
        ))
    return candidates


def filter_by_sectors(
    candidates: list[Candidate],
    allowed_sectors: list[str],
) -> list[Candidate]:
    return [c for c in candidates if c.stock.sector in allowed_sectors]


def filter_by_bucket(
    candidates: list[Candidate],
    allowed_buckets: list[str],
) -> list[Candidate]:
    return [c for c in candidates if c.bucket in allowed_buckets]


def rank_candidates(
    candidates: list[Candidate],
    max_results: int = 5,
) -> list[Candidate]:
    if not candidates:
        return []

    def score(c: Candidate) -> float:
        wr = c.wr_event or 0
        pot = c.potential or 0
        dd = abs(c.drawdown or 0)
        risk_penalty = 0
        if "risiko" in c.note.lower() or "distribusi" in c.note.lower():
            risk_penalty = 10
        return wr * 0.5 + pot * 0.3 - dd * 0.2 - risk_penalty

    sorted_candidates = sorted(candidates, key=score, reverse=True)
    return sorted_candidates[:max_results]
```

- [x] **Step 4: Run tests to verify they pass**

Run: `cd /root/projects/screener_ihsg && python -m pytest tests/test_screener.py -v`
Expected: 7 tests PASS

- [x] **Step 5: Commit**

```bash
cd /root/projects/screener_ihsg
git add src/screener.py tests/test_screener.py
git commit -m "feat: add screening pipeline with sector filter and candidate ranking"
```

---

### Task 5: Validator (Deep Analysis per Candidate)

**Files:**
- Create: `src/validator.py`
- Create: `tests/test_validator.py`

**Interfaces:**
- Consumes:
  - `models.Candidate`, `models.Stock`, `models.OHLCRow`, `models.ValidationResult`, `models.TradePlan`, `models.PivotLevels` (from Task 1)
  - `pivot.calculate_pivot()`, `pivot.calculate_atr()`, `pivot.calculate_trade_plan()` (from Task 1)
  - `mcp_client.McpClient` (from Task 2)
- Produces:
  - `build_validation_request_list(candidate: Candidate) -> list[McpCallRequest]` returns the list of MCP calls needed for deep validation
  - `parse_foreign_flow_5d(ohlc_rows: list[OHLCRow]) -> list[float]` returns last 5 days of n_foreign
  - `assemble_validation(candidate: Candidate, analysis_text: str, broker_data: dict, ohlc_rows: list[OHLCRow]) -> ValidationResult`
  - `format_validation_summary(result: ValidationResult) -> str`

- [x] **Step 1: Write failing tests for validator**

```python
# tests/test_validator.py
import unittest
from src.validator import (
    parse_foreign_flow_5d,
    assemble_validation,
    format_validation_summary,
)
from src.models import Candidate, Stock, OHLCRow, ValidationResult


class TestValidator(unittest.TestCase):
    def setUp(self):
        self.stock = Stock(code="BBCA", name="Bank Central Asia Tbk.", sector="Financials")
        self.candidate = Candidate(
            stock=self.stock,
            bucket="SINYAL BERSIH",
            summary="asing beli kuat",
            wr_event=74.1,
            potential=11.0,
            drawdown=-5.0,
        )
        self.ohlc_rows = [
            OHLCRow(date=f"2026-09-{25-i:02d}", open=6225, high=6275,
                    low=6200, close=6250-i*25, volume=89e6, value=558e9,
                    f_buy=73e6, f_sell=57e6, n_foreign=16.5e6 - i * 5e6)
            for i in range(20)
        ]

    def test_parse_foreign_flow_5d(self):
        flows = parse_foreign_flow_5d(self.ohlc_rows)
        self.assertEqual(len(flows), 5)
        self.assertEqual(flows[0], self.ohlc_rows[0].n_foreign)

    def test_parse_foreign_flow_short_data(self):
        short = self.ohlc_rows[:3]
        flows = parse_foreign_flow_5d(short)
        self.assertEqual(len(flows), 3)

    def test_assemble_validation(self):
        result = assemble_validation(
            candidate=self.candidate,
            analysis_text="Test analysis",
            broker_data={"brokers": []},
            ohlc_rows=self.ohlc_rows,
        )
        self.assertIsInstance(result, ValidationResult)
        self.assertIsNotNone(result.pivot)
        self.assertIsNotNone(result.trade_plan)
        self.assertGreater(result.trade_plan.rr_ratio, 1.0,
                           "R:R must be > 1.0 (asymmetric ATR)")

    def test_format_validation_not_empty(self):
        result = assemble_validation(
            candidate=self.candidate,
            analysis_text="Test analysis text",
            broker_data={"brokers": []},
            ohlc_rows=self.ohlc_rows,
        )
        text = format_validation_summary(result)
        self.assertIn("BBCA", text)
        self.assertIn("Trade Plan", text)
        self.assertGreater(len(text), 100)

    def test_format_includes_foreign_flow(self):
        result = assemble_validation(
            candidate=self.candidate,
            analysis_text="Test",
            broker_data={"brokers": []},
            ohlc_rows=self.ohlc_rows,
        )
        text = format_validation_summary(result)
        self.assertIn("Foreign Flow", text)
        self.assertNotIn("Money Flow", text,
                         "Must use 'Foreign Flow', not 'Money Flow' (data honesty)")


if __name__ == "__main__":
    unittest.main()
```

- [x] **Step 2: Run test to verify it fails**

Run: `cd /root/projects/screener_ihsg && python -m pytest tests/test_validator.py -v`
Expected: FAIL with "ModuleNotFoundError"

- [x] **Step 3: Implement validator**

```python
# src/validator.py
from src.models import (
    Candidate, OHLCRow, ValidationResult, TradePlan, PivotLevels,
)
from src.pivot import calculate_pivot, calculate_atr, calculate_trade_plan
from src.mcp_client import McpCallRequest


def build_validation_request_list(candidate: Candidate) -> list[McpCallRequest]:
    code = candidate.stock.code
    return [
        McpCallRequest(tool_name="analisa_saham", arguments={"code": code}),
        McpCallRequest(
            tool_name="broker_summary",
            arguments={"code": code, "flow": "all", "broker_limit": 10},
        ),
        McpCallRequest(
            tool_name="riwayat_harga",
            arguments={
                "code": code, "limit": 60, "frame": "daily",
                "fields": "date,open,high,low,close,volume,value,f_buy,f_sell,n_foreign",
            },
        ),
        McpCallRequest(
            tool_name="akumulasi_broker_historis",
            arguments={"code": code, "top": 3},
        ),
        # analisa_saham already includes PER/PBV/DER from server-side analysis,
        # but PRD §7.4 asks for deeper fundamentals (EPS growth, NAV, dividend yield).
        # report_type="all" costs 3 quota (one per financial statement).
        McpCallRequest(
            tool_name="laporan_keuangan",
            arguments={"code": code, "report_type": "all", "period": "quarterly", "limit": 4},
        ),
    ]


def parse_foreign_flow_5d(ohlc_rows: list[OHLCRow]) -> list[float]:
    return [row.n_foreign for row in ohlc_rows[:5]]


def assemble_validation(
    candidate: Candidate,
    analysis_text: str,
    broker_data: dict,
    ohlc_rows: list[OHLCRow],
) -> ValidationResult:
    latest = ohlc_rows[0] if ohlc_rows else None
    pivot = None
    trade_plan = None
    foreign_flow_5d = parse_foreign_flow_5d(ohlc_rows)

    if latest:
        pivot = calculate_pivot(latest.high, latest.low, latest.close)
        atr = calculate_atr(ohlc_rows, period=14) if len(ohlc_rows) >= 15 else (latest.high - latest.low)
        trade_plan = calculate_trade_plan(
            close=latest.close,
            atr=atr,
            support=pivot.s1 if pivot else latest.low,
        )

    return ValidationResult(
        stock=candidate.stock,
        analysis_text=analysis_text,
        broker_data=broker_data,
        foreign_flow_5d=foreign_flow_5d,
        pivot=pivot,
        trade_plan=trade_plan,
    )


def format_validation_summary(result: ValidationResult) -> str:
    lines = []
    lines.append(f"## {result.stock.code} - {result.stock.name}")
    lines.append(f"**Sector:** {result.stock.sector}")
    lines.append("")

    lines.append("### Analysis")
    lines.append(result.analysis_text)
    lines.append("")

    lines.append("### Net Foreign Flow (5D)")
    if result.foreign_flow_5d:
        for i, flow in enumerate(result.foreign_flow_5d):
            direction = "BUY" if flow > 0 else "SELL"
            lines.append(f"  D-{i}: {flow:+,.0f} shares ({direction})")
    else:
        lines.append("  No data available")
    lines.append("")

    if result.pivot:
        p = result.pivot
        lines.append("### Pivot Levels")
        lines.append(f"  R3: {p.r3:,.0f} | R2: {p.r2:,.0f} | R1: {p.r1:,.0f}")
        lines.append(f"  Pivot: {p.pivot:,.0f}")
        lines.append(f"  S1: {p.s1:,.0f} | S2: {p.s2:,.0f} | S3: {p.s3:,.0f}")
        lines.append("")

    if result.trade_plan:
        tp = result.trade_plan
        lines.append("### Trade Plan")
        lines.append(f"  Entry Range: {tp.entry_low:,.0f} - {tp.entry_high:,.0f}")
        lines.append(f"  Cutloss: {tp.cutloss:,.0f} (1x ATR)")
        lines.append(f"  Target 1: {tp.target1:,.0f} (1.5x ATR)")
        lines.append(f"  Target 2: {tp.target2:,.0f} (2x ATR)")
        lines.append(f"  R:R Ratio: {tp.rr_ratio}:1")
        lines.append(f"  ATR(14): {tp.atr:,.2f}")
        lines.append("")

    if result.broker_data.get("brokers"):
        lines.append("### Top Brokers")
        for b in result.broker_data["brokers"][:5]:
            code = b.get("broker_code", "?")
            name = b.get("broker_name", "")
            nval = b.get("nval", 0)
            direction = "NET BUY" if nval > 0 else "NET SELL"
            lines.append(f"  {code} ({name}): {nval/1e9:+,.2f}B ({direction})")
        lines.append("")

    return "\n".join(lines)
```

- [x] **Step 4: Run tests to verify they pass**

Run: `cd /root/projects/screener_ihsg && python -m pytest tests/test_validator.py -v`
Expected: 5 tests PASS

- [x] **Step 5: Commit**

```bash
cd /root/projects/screener_ihsg
git add src/validator.py tests/test_validator.py
git commit -m "feat: add deep validation module with honest foreign flow labeling"
```

---

### Task 6: Report Generator

**Files:**
- Create: `src/report.py`
- Create: `tests/test_report.py`

**Interfaces:**
- Consumes:
  - `models.Candidate`, `models.ValidationResult`, `models.RRGPoint` (from Task 1)
  - `validator.format_validation_summary()` (from Task 5)
  - `sector_rrg.rank_sectors()` (from Task 3)
- Produces:
  - `generate_daily_report(date: str, sector_ranking: list[tuple], candidates: list[Candidate], validations: list[ValidationResult], quota_used: int) -> str`
  - `save_report(content: str, output_dir: str) -> str` returns path to saved file

- [x] **Step 1: Write failing tests for report generation**

```python
# tests/test_report.py
import unittest
import tempfile
from pathlib import Path
from src.report import generate_daily_report, save_report
from src.models import (
    Candidate, Stock, ValidationResult, PivotLevels, TradePlan,
)


class TestReport(unittest.TestCase):
    def setUp(self):
        self.sector_ranking = [
            ("Financials", "Leading", 3.5),
            ("Energy", "Improving", 2.8),
        ]
        self.stock = Stock(code="BBCA", name="Bank Central Asia Tbk.", sector="Financials")
        self.candidates = [
            Candidate(stock=self.stock, bucket="SINYAL BERSIH",
                      summary="asing beli kuat", wr_event=74.1,
                      potential=11.0, drawdown=-5.0),
        ]
        self.validations = [
            ValidationResult(
                stock=self.stock,
                analysis_text="Strong buy signal",
                broker_data={"brokers": []},
                foreign_flow_5d=[16.5e6, 1.1e6, -2.7e6],
                pivot=PivotLevels(pivot=6242, r1=6283, r2=6317, r3=6358,
                                  s1=6208, s2=6167, s3=6133),
                trade_plan=TradePlan(entry_low=6200, entry_high=6250,
                                    cutloss=6114, target1=6454,
                                    target2=6522, rr_ratio=1.5, atr=136),
            ),
        ]

    def test_report_contains_date(self):
        report = generate_daily_report(
            "2026-09-27", self.sector_ranking, self.candidates, self.validations, 25)
        self.assertIn("2026-09-27", report)

    def test_report_contains_sector_ranking(self):
        report = generate_daily_report(
            "2026-09-27", self.sector_ranking, self.candidates, self.validations, 25)
        self.assertIn("Financials", report)
        self.assertIn("Leading", report)

    def test_report_contains_candidates(self):
        report = generate_daily_report(
            "2026-09-27", self.sector_ranking, self.candidates, self.validations, 25)
        self.assertIn("BBCA", report)

    def test_report_contains_trade_plan(self):
        report = generate_daily_report(
            "2026-09-27", self.sector_ranking, self.candidates, self.validations, 25)
        self.assertIn("Trade Plan", report)
        self.assertIn("1.5:1", report)

    def test_report_shows_quota(self):
        report = generate_daily_report(
            "2026-09-27", self.sector_ranking, self.candidates, self.validations, 25)
        self.assertIn("25", report)

    def test_report_no_false_money_flow_label(self):
        report = generate_daily_report(
            "2026-09-27", self.sector_ranking, self.candidates, self.validations, 25)
        self.assertNotIn("Money Flow", report)

    def test_empty_candidates_still_generates(self):
        report = generate_daily_report(
            "2026-09-27", self.sector_ranking, [], [], 5)
        self.assertIn("2026-09-27", report)
        self.assertIn("Tidak ada kandidat", report)

    def test_save_report(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            content = "# Test Report"
            path = save_report(content, tmpdir)
            self.assertTrue(Path(path).exists())
            self.assertTrue(path.endswith(".md"))


if __name__ == "__main__":
    unittest.main()
```

- [x] **Step 2: Run test to verify it fails**

Run: `cd /root/projects/screener_ihsg && python -m pytest tests/test_report.py -v`
Expected: FAIL with "ModuleNotFoundError"

- [x] **Step 3: Implement report generator**

```python
# src/report.py
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
        lines.append("| Rank | Sektor | Kuadran | Skor |")
        lines.append("|------|--------|---------|------|")
        for i, (sector, quadrant, score) in enumerate(sector_ranking, 1):
            lines.append(f"| {i} | {sector} | {quadrant} | {score} |")
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
```

- [x] **Step 4: Run tests to verify they pass**

Run: `cd /root/projects/screener_ihsg && python -m pytest tests/test_report.py -v`
Expected: 8 tests PASS

- [x] **Step 5: Commit**

```bash
cd /root/projects/screener_ihsg
git add src/report.py tests/test_report.py
git commit -m "feat: add Markdown report generator with sector ranking and trade plans"
```

---

### Task 7: CLI Orchestrator (main.py)

**Files:**
- Create: `src/main.py`

**Interfaces:**
- Consumes: all modules from Tasks 1-6
- Produces: `run_pipeline() -> str` that returns the path to the saved report

This module ties everything together. It cannot be unit-tested in the traditional sense because it depends on live MCP calls. Instead, this task is a smoke test: run the pipeline against the live API with 1-2 sectors and verify a report is generated.

- [x] **Step 1: Create main.py orchestrator**

```python
# src/main.py
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


# These are the MCP calls the agent needs to execute.
# The agent calls each tool and feeds results back into the pipeline.

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
```

- [x] **Step 2: Run smoke test**

Run: `cd /root/projects/screener_ihsg && python -c "from src.main import create_pipeline_config; c = create_pipeline_config(); print(f'OK: {len(c[\"sector_config\"])} sectors, date={c[\"date\"]}')""`
Expected: `OK: 11 sectors, date=2026-09-27`

- [x] **Step 3: Run full test suite**

Run: `cd /root/projects/screener_ihsg && python -m pytest tests/ -v --tb=short`
Expected: All tests PASS (across test_pivot, test_models, test_sector_rrg, test_screener, test_validator, test_report)

- [x] **Step 4: Commit**

```bash
cd /root/projects/screener_ihsg
git add src/main.py
git commit -m "feat: add CLI orchestrator with pipeline step documentation"
```

- [x] **Step 5: Create output directory**

```bash
mkdir -p /root/projects/screener_ihsg/output
echo "*.md" > /root/projects/screener_ihsg/output/.gitignore
git add output/.gitignore
git commit -m "chore: add output directory for generated reports"
```

---

## Quota Budget Summary

| Step | Calls | Notes |
|------|-------|-------|
| Screener | 1 | Zero-param call, cached for ~24hr |
| Benchmark OHLC | 1 | COMPOSITE or proxy |
| Sector RRG (worst case) | 55 | 5 stocks x 11 sectors, or batched |
| Sector RRG (batched) | 11 | 1 harga_batch per sector |
| Validation (5 candidates) | 35 | 4 calls + laporan_keuangan(3 quota) x 5 |
| **Total (batched)** | **~48** | Well under 1000/hr |
| **Total (unbatched worst)** | **~92** | Still well under limit |

---

## What This Plan Does NOT Build (Fase 2/3)

- **Modul Order Flow (§7.6)**: `done_details` data is confirmed usable (tick-level, timestamped, with buyer/seller classification). Build after v1 is stable.
- **Real-time alerts**: Out of scope per PRD §4.
- **Auto-trading**: Out of scope per PRD §4.
- **Web UI**: This is a CLI/script tool per PRD §3.
