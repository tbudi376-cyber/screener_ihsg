import re
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
        McpCallRequest(
            tool_name="laporan_keuangan",
            arguments={"code": code, "report_type": "all", "period": "quarterly", "limit": 4},
        ),
    ]


def parse_foreign_flow_5d(ohlc_rows: list[OHLCRow]) -> list[tuple[float, float]]:
    """Parse net foreign flow for the latest 5 trading days with estimated Rupiah value.

    Official system convention: ohlc_rows is ordered oldest-to-newest.
    Returns [(shares_D0, rupiah_D0), (shares_D1, rupiah_D1), ...]
    where D0 is the most recent trading day (ohlc_rows[-1]).
    Estimated Rupiah value is calculated as: n_foreign * close_price.
    """
    if not ohlc_rows:
        return []
    recent_5 = ohlc_rows[-5:]
    results = []
    # Reverse to produce D-0 (latest), D-1, D-2, D-3, D-4
    for row in reversed(recent_5):
        shares = row.n_foreign
        rupiah_val = shares * row.close
        results.append((shares, rupiah_val))
    return results


def format_rupiah_compact(val: float) -> str:
    """Format Rupiah value into clean compact string (Rp...B or Rp...M)."""
    sign = "+" if val > 0 else "-"
    abs_val = abs(val)
    if abs_val >= 1e12:
        return f"{sign}Rp{abs_val / 1e12:,.2f}T"
    elif abs_val >= 1e9:
        return f"{sign}Rp{abs_val / 1e9:,.2f}B"
    elif abs_val >= 1e6:
        return f"{sign}Rp{abs_val / 1e6:,.2f}M"
    else:
        return f"{sign}Rp{abs_val:,.0f}"


def extract_fundamental_metrics(fin_data: dict, close_price: float = 0.0) -> dict:
    """Extract key fundamental metrics from laporan_keuangan (INCOME_STATEMENT & BALANCE_SHEET)."""
    metrics = {
        "eps": None,
        "per": None,
        "der": None,
        "revenue": None,
        "net_income": None,
        "equity": None,
        "revenue_growth_yoy": None,
        "net_income_growth_yoy": None,
    }
    if not fin_data:
        return metrics

    inc = fin_data.get("INCOME_STATEMENT", {})
    bal = fin_data.get("BALANCE_SHEET", {})

    inc_items = inc.get("items", [])
    bal_items = bal.get("items", [])

    if inc_items:
        latest_inc = inc_items[0].get("data", {})
        rev = latest_inc.get("penjualan_dan_pendapatan_usaha")
        net = latest_inc.get("laba_rugi")
        eps_data = latest_inc.get("laba_rugi_per_saham", {}).get(
            "laba_per_saham_dasar_diatribusikan_kepada_pemilik_entitas_induk", {}
        )
        eps = eps_data.get("total")
        if not eps or eps == 0.0:
            eps = eps_data.get("laba_rugi_per_saham_dasar_dari_operasi_yang_dilanjutkan")

        metrics["revenue"] = rev
        metrics["net_income"] = net
        metrics["eps"] = eps

        # Calculate YoY growth if previous year/quarter is available
        if len(inc_items) > 1:
            prev_inc = inc_items[1].get("data", {})
            prev_rev = prev_inc.get("penjualan_dan_pendapatan_usaha")
            prev_net = prev_inc.get("laba_rugi")
            if rev is not None and prev_rev and prev_rev > 0:
                metrics["revenue_growth_yoy"] = round((rev - prev_rev) / prev_rev * 100, 2)
            if net is not None and prev_net and prev_net != 0:
                metrics["net_income_growth_yoy"] = round((net - prev_net) / abs(prev_net) * 100, 2)

    if bal_items:
        latest_bal = bal_items[0].get("data", {})
        liab = latest_bal.get("liabilitas_dan_ekuitas", {}).get("liabilitas", {}).get("total")
        eq = latest_bal.get("liabilitas_dan_ekuitas", {}).get("ekuitas", {}).get("total")
        metrics["equity"] = eq
        if liab is not None and eq and eq > 0:
            metrics["der"] = round(liab / eq, 2)

    # Guard against zero, near-zero, or negative EPS producing misleading astronomical PER
    EPS_MIN_THRESHOLD = 1.0  # Annualized EPS < Rp1.0/share or EPS <= 0 is Not Meaningful (N/M)
    if metrics["eps"] is not None:
        annualized_eps = metrics["eps"] * 4
        if metrics["eps"] <= 0 or annualized_eps < EPS_MIN_THRESHOLD:
            metrics["per"] = "N/M"
        elif close_price:
            metrics["per"] = round(close_price / annualized_eps, 2)

    return metrics


def extract_personality_wr_stats(analysis_text: str) -> dict:
    """Extract historical Win Rate (WR Event) statistics from Personality Historis in analysis text.

    A pattern is considered to have a sufficiently large sample size if its tag is NOT 'SAMPEL KECIL'
    (e.g., 'SAMPEL VALID', 'EDGE HISTORIS').

    Returns:
        dict: {
            "patterns": list of all parsed patterns,
            "valid_patterns": list of patterns with sufficient sample size,
            "avg_wr": average WR Event of valid patterns (float | None),
            "is_weak_history": bool (True if valid patterns exist and avg_wr < 50.0),
            "flag": warning string (e.g., '44.6% ⚠️ Historis Lemah') or None,
        }
    """
    result = {
        "patterns": [],
        "valid_patterns": [],
        "avg_wr": None,
        "is_weak_history": False,
        "flag": None,
    }
    if not analysis_text or "PERSONALITY HISTORIS" not in analysis_text:
        return result

    section = analysis_text.split("PERSONALITY HISTORIS", 1)[1]
    for stop_word in ["REKOMENDASI", "DISCLAIMER", "###"]:
        if stop_word in section:
            section = section.split(stop_word, 1)[0]

    pattern_regex = re.compile(
        r'(\d+)\.\s+([^\n—–-]+)\s*[—–-]\s*\*{0,2}([^\n*]+)\*{0,2}(.*?)(?=\n\s*\d+\.|\n\s*💡|\n\s*\*\*|\Z)',
        re.DOTALL,
    )

    items = pattern_regex.findall(section)
    for num, title, tag, body in items:
        clean_tag = tag.strip().upper()
        wr_match = re.search(r'WR\s+Event\s*([\d\.]+)%', body, re.IGNORECASE)
        sample_match = re.search(r'Sample\s*(\d+)', body, re.IGNORECASE)

        wr_val = float(wr_match.group(1)) if wr_match else None
        sample_size = int(sample_match.group(1)) if sample_match else None

        is_valid = True
        if "SAMPEL KECIL" in clean_tag or "KECIL" in clean_tag:
            is_valid = False

        pat_info = {
            "num": int(num),
            "title": title.strip(),
            "tag": tag.strip(),
            "wr_event": wr_val,
            "sample_size": sample_size,
            "is_valid_sample": is_valid,
        }
        result["patterns"].append(pat_info)
        if is_valid and wr_val is not None:
            result["valid_patterns"].append(pat_info)

    if result["valid_patterns"]:
        valid_wrs = [p["wr_event"] for p in result["valid_patterns"]]
        avg_wr = sum(valid_wrs) / len(valid_wrs)
        result["avg_wr"] = round(avg_wr, 1)
        if avg_wr < 50.0:
            result["is_weak_history"] = True
            result["flag"] = f"{avg_wr:.1f}% ⚠️ Historis Lemah"

    return result


def assemble_validation(
    candidate: Candidate,
    analysis_text: str,
    broker_data: dict,
    ohlc_rows: list[OHLCRow],
    fundamental_data: dict | None = None,
    fallback_reason: str = "",
) -> ValidationResult:
    # Official convention: ohlc_rows is ordered oldest-to-newest, so index -1 is the latest candle
    latest = ohlc_rows[-1] if ohlc_rows else None
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
            pivot_levels=pivot,
        )

    personality_stats = extract_personality_wr_stats(analysis_text)
    if personality_stats.get("avg_wr") is not None:
        if candidate.wr_event is None:
            candidate.wr_event = personality_stats["avg_wr"]
    if personality_stats.get("is_weak_history"):
        wr_disp = candidate.wr_event if candidate.wr_event is not None else personality_stats["avg_wr"]
        candidate.wr_event_flag = f"{wr_disp:.1f}% ⚠️ Historis Lemah"
    elif candidate.wr_event is not None and candidate.wr_event < 50.0:
        candidate.wr_event_flag = f"{candidate.wr_event:.1f}% ⚠️ Historis Lemah"

    return ValidationResult(
        stock=candidate.stock,
        analysis_text=analysis_text,
        broker_data=broker_data,
        foreign_flow_5d=foreign_flow_5d,
        pivot=pivot,
        trade_plan=trade_plan,
        fundamental_data=fundamental_data or {},
        fallback_reason=fallback_reason,
        personality_stats=personality_stats,
    )


def format_validation_summary(result: ValidationResult) -> str:
    lines = []
    lines.append(f"## {result.stock.code} - {result.stock.name}")
    lines.append(f"**Sector:** {result.stock.sector}")
    lines.append("")

    if result.personality_stats.get("is_weak_history"):
        avg_wr = result.personality_stats.get("avg_wr")
        lines.append(f"⚠️ **PERINGATAN HISTORIS**: Rata-rata Win Rate event masa lalu {avg_wr:.1f}% (< 50%). Sinyal memiliki probabilitas historis rendah.")
        lines.append("")

    if result.fallback_reason:
        lines.append("### Catatan Validasi")
        lines.append(f"ℹ️ {result.fallback_reason}")
        lines.append("")

    if result.analysis_text:
        lines.append("### Analysis")
        lines.append(result.analysis_text)
        lines.append("")

    if result.fundamental_data:
        f = result.fundamental_data
        lines.append("### Fundamental & Valuasi")
        parts = []
        if f.get("eps") is not None:
            eps_val = f["eps"]
            if 0 < abs(eps_val) < 1.0:
                parts.append(f"EPS: Rp{eps_val:.2f}")
            else:
                parts.append(f"EPS: Rp{eps_val:,.0f}")
        if f.get("per") is not None:
            if f["per"] == "N/M":
                parts.append("PER: N/M (Not Meaningful)")
            else:
                parts.append(f"PER: {f['per']}x")
        if f.get("der") is not None:
            parts.append(f"DER: {f['der']}x")
        if f.get("revenue_growth_yoy") is not None:
            parts.append(f"Pertumbuhan Pendapatan (YoY): {f['revenue_growth_yoy']:+,.1f}%")
        if f.get("net_income_growth_yoy") is not None:
            parts.append(f"Pertumbuhan Laba Bersih (YoY): {f['net_income_growth_yoy']:+,.1f}%")

        if parts:
            for p in parts:
                lines.append(f"  • {p}")
        else:
            lines.append("  Data rasio keuangan belum lengkap di periode pelaporan terakhir.")
        lines.append("")

    lines.append("### Net Foreign Flow (5D)")
    if result.foreign_flow_5d:
        for i, item in enumerate(result.foreign_flow_5d):
            if isinstance(item, (list, tuple)):
                shares = item[0]
                idr_str = f" ({format_rupiah_compact(item[1])})"
            else:
                shares = float(item)
                idr_str = ""
            direction = "BUY" if shares > 0 else "SELL"
            lines.append(f"  D-{i}: {shares:+,.0f} shares{idr_str} ({direction})")
    else:
        lines.append("  Data foreign flow harian tidak ditarik untuk saham ini.")
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
        lines.append("### Trade Plan (Fraksi BEI)")
        lines.append(f"  Entry Range: Rp{tp.entry_low:,.0f} - Rp{tp.entry_high:,.0f}")
        lines.append(f"  Cutloss: Rp{tp.cutloss:,.0f} (Proteksi di bawah Entry Range)")
        lines.append(f"  Target 1: Rp{tp.target1:,.0f} (Resisten Terdekat)")
        lines.append(f"  Target 2: Rp{tp.target2:,.0f} (Resisten Lanjutan)")
        lines.append(f"  R:R Ratio: {tp.rr_ratio}:1")
        lines.append(f"  ATR(14): Rp{tp.atr:,.2f}")
        if tp.warning:
            lines.append(f"  {tp.warning}")
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
