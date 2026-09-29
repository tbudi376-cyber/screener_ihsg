# AGENTS.md — Screener Saham IHSG (`screener_ihsg`)

Repository guidance for AI coding agents. Read before modifying code, executing pipelines, or conducting audits.

## 1. Dual-Agent Roles

Every agent invocation belongs to one of two roles:

- **AI Implementor (Code Executor)**:
  - Writes and edits code in `src/`, unit tests in `tests/`, and pipeline scripts.
  - Executes screening runs and fixes bugs reported by audits.
  - Gate: Must achieve 100% passing tests via `pytest` before declaring any task complete.
- **AI Reviewer (Audit Only)**:
  - Inspects reports in `output/` and code diffs (`git diff origin/main...HEAD`).
  - Audits compliance against IDX regulations and PRD philosophy.
  - Hard constraint: Never edit codebase files directly. Formats structured findings for the Product Owner (Tubagus Budi) to pass to the Implementor.
  - Pointer: Detailed audit checklist lives in [`Handover dan Panduan Kerja AI Reviewer.md`](file:///sdcard/Download/Handover%20dan%20Panduan%20Kerja%20AI%20Reviewer.md).

## 2. Technical Invariants

- **Runtime**: Python 3.11+ Standard Library ONLY. No third-party pip dependencies in `v1`.
- **Data Provider**: MCP server `idx-edge` (`stock.arjum.com`).
- **Quota Ceiling**: Maximum 1,000 requests/hour. A healthy pipeline run consumes 70–85 requests. Cache OHLC during RRG step to avoid duplicate calls.
- **File Encoding**: Explicit `encoding="utf-8"` on all file read/write operations.

## 3. Financial & Domain Guardrails

1. **IDX Price Tick Fractions (Kep-00023/BEI/03-2020)**:
   All Trade Plan levels (Entry, Cutloss, Target 1, Target 2, Pivot) must round to official IDX ticks:
   - `< Rp200`: step Rp1
   - `Rp200 – < Rp500`: step Rp2
   - `Rp500 – < Rp2.000`: step Rp5
   - `Rp2.000 – < Rp5.000`: step Rp10
   - `≥ Rp5.000`: step Rp25
2. **Chronological Time-Series**:
   All OHLC rows are strictly ordered `oldest-to-newest` (index `-1` is latest candle). Never invert chronological order when computing EMAs or ATRs.
3. **AVOID & Low Win Rate Protection**:
   If stock is marked `AVOID / HINDARI`, score `≤ 25/75`, or historical event Win Rate `< 50%`:
   - Status locked to: `TIDAK DIREKOMENDASIKAN (Sinyal AVOID / Tekanan Jual Kuat)`.
   - Entry Range set to: `TIDAK DISARANKAN ENTRY`.
   - Never print `TUNGGU (Buy on Weakness)` or active buy bands (`mantul/hold Rp...`). Cutloss serves purely as protection for existing holders.
4. **Dynamic R:R & Maximum Entry**:
   - Enforce `Batas Entry Maksimum (R:R 1.0:1)` via formula: $E \le \frac{T_1 + k \cdot Cutloss}{1 + k}$.
   - Cutloss must always strictly sit below the lower bound of Entry Range.
5. **Data Integrity (PRD §8)**:
   - Foreign flow must be labeled as **Net Foreign Flow** (`n_foreign` shares and estimated Rp), never "Money Flow".
   - Stale fundamental data (>3 quarters old) must carry `⚠️ Data Fundamental Sangat Basi`.
   - Point to domain glossary: [`docs/kamus_metrik.md`](file:///root/projects/screener_ihsg/docs/kamus_metrik.md).

## 4. Dual Screening Modes

The orchestrator (`src/main.py`) supports two distinct execution modes:

- **Mode Upstream (`mode="upstream"`, default)**:
  - Source: `idx-edge:screener_saham_terkini` (entire market) intersected with RRG Leading/Improving sectors.
  - Bucket: `SINYAL BERSIH` and `SINYAL SENYAP`.
  - Output files: `output/screener_upstream_YYYY-MM-DD.md` (and legacy `screener_YYYY-MM-DD.md`).
- **Mode Mandiri (`mode="mandiri"`, explicit sore run)**:
  - Source: Constituent stocks of Leading/Improving sectors from `config/sectors.json`.
  - Strict 4/4 Filter (PRD §6):
    1. Daily transaction value $\ge \text{Rp}1\text{ Miliar}$ (`latest.value >= 1e9`)
    2. Daily volume $>$ SMA20 volume (`latest.volume > sma20_vol`)
    3. Daily Net Foreign Buy $> 0$ (`latest.n_foreign > 0` or `f_buy > f_sell`)
    4. Close $\ge$ SMA20 close (`latest.close >= sma20_close`)
    5. Anti-ARB/ARA: `latest.high > latest.low`
  - Output file: `output/screener_mandiri_YYYY-MM-DD.md`.
- **Sync Targets**:
  - Mirror output files to `/sdcard/Download/` with standard latest symlinks (`screener_upstream_terbaru.md`, `screener_mandiri_terbaru.md`, and `screener_ihsg_terbaru.md`).

## 5. Verification Gate

Before completing any task or committing changes:
```bash
pytest -v
```
- **Completion Criterion**: 100% of tests in `tests/` pass with zero failures or errors.
- Any change to screening criteria or trade plan math must be accompanied by matching unit tests.
