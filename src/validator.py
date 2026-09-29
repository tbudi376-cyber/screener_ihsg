import re
import statistics
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
            arguments={"code": code, "report_type": "all", "period": "quarterly", "limit": 8},
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


def expand_abbreviated_prices(
    text: str,
    ohlc_rows: list[OHLCRow],
    pivot_levels: PivotLevels | None = None,
) -> str:
    """Replace abbreviated price labels like 'Rp15K' with precise values from OHLC data and PivotLevels.
    
    The analisa_saham API returns pre-formatted text that rounds high prices to 'RpNK'
    format, losing the actual value differences between Prev/Open/High/Low and Pivot levels.
    """
    if not ohlc_rows or not text:
        return text
    latest = ohlc_rows[-1] if ohlc_rows else None
    prev = ohlc_rows[-2] if len(ohlc_rows) >= 2 else None
    if not latest:
        return text

    # 1. Main price header (e.g. '🟢 **Rp15K**' -> '🟢 **Rp15,000**')
    text = re.sub(
        r"([🟢🔴])\s*\*\*Rp[\d\.,]+[KMB]?\*\*",
        lambda m: f"{m.group(1)} **Rp{latest.close:,.0f}**",
        text,
        count=1,
    )

    # 2. Prev, Open, High, Low
    prev_val = prev.close if prev else latest.open
    text = re.sub(
        r"Prev\s*:\s*Rp[\d\.,]+[KMB]?",
        f"Prev: Rp{prev_val:,.0f}",
        text,
        count=1,
    )
    text = re.sub(
        r"Open\s*:\s*Rp[\d\.,]+[KMB]?",
        f"Open: Rp{latest.open:,.0f}",
        text,
        count=1,
    )
    text = re.sub(
        r"High\s*:\s*Rp[\d\.,]+[KMB]?",
        f"High: Rp{latest.high:,.0f}",
        text,
        count=1,
    )
    text = re.sub(
        r"Low\s*:\s*Rp[\d\.,]+[KMB]?",
        f"Low: Rp{latest.low:,.0f}",
        text,
        count=1,
    )

    # 3. Support & Resistance Daily line if PivotLevels available
    if pivot_levels:
        text = re.sub(
            r"Daily:\s*R2\s*Rp[\d\.,]+[KMB]?\s*\|\s*R1\s*Rp[\d\.,]+[KMB]?\s*\|\s*P\s*Rp[\d\.,]+[KMB]?\s*\|\s*S1\s*Rp[\d\.,]+[KMB]?\s*\|\s*S2\s*Rp[\d\.,]+[KMB]?",
            f"Daily: R2 Rp{pivot_levels.r2:,.0f} | R1 Rp{pivot_levels.r1:,.0f} | P Rp{pivot_levels.pivot:,.0f} | S1 Rp{pivot_levels.s1:,.0f} | S2 Rp{pivot_levels.s2:,.0f}",
            text,
            count=1,
        )

    # 4. TEKNIKAL: SMA5, SMA20, SMA50
    closes = [r.close for r in ohlc_rows]
    if len(closes) >= 5:
        sma5 = sum(closes[-5:]) / 5.0
        if len(closes) >= 20:
            sma20 = sum(closes[-20:]) / 20.0
            if len(closes) >= 50:
                sma50 = sum(closes[-50:]) / 50.0
                text = re.sub(
                    r"SMA5\s*:\s*Rp[\d\.,]+[KMB]?\s*\|\s*SMA20\s*:\s*Rp[\d\.,]+[KMB]?\s*\|\s*SMA50\s*:\s*Rp[\d\.,]+[KMB]?",
                    f"SMA5: Rp{sma5:,.0f} | SMA20: Rp{sma20:,.0f} | SMA50: Rp{sma50:,.0f}",
                    text,
                    count=1,
                )
            else:
                text = re.sub(
                    r"SMA5\s*:\s*Rp[\d\.,]+[KMB]?\s*\|\s*SMA20\s*:\s*Rp[\d\.,]+[KMB]?",
                    f"SMA5: Rp{sma5:,.0f} | SMA20: Rp{sma20:,.0f}",
                    text,
                    count=1,
                )

    # 5. TEKNIKAL: Bollinger Bands BB(20,2)
    if len(closes) >= 20:
        sma20 = sum(closes[-20:]) / 20.0
        stdev = statistics.stdev(closes[-20:])
        bb_upper = sma20 + 2 * stdev
        bb_lower = sma20 - 2 * stdev
        text = re.sub(
            r"BB\(20,2\)\s*:\s*Upper\s*Rp[\d\.,]+[KMB]?\s*\|\s*Mid\s*Rp[\d\.,]+[KMB]?\s*\|\s*Lower\s*Rp[\d\.,]+[KMB]?",
            f"BB(20,2): Upper Rp{bb_upper:,.0f} | Mid Rp{sma20:,.0f} | Lower Rp{bb_lower:,.0f}",
            text,
            count=1,
        )

    return text


def extract_fundamental_metrics(fin_data: dict, close_price: float = 0.0) -> dict:
    """Extract key fundamental metrics from laporan_keuangan (INCOME_STATEMENT & BALANCE_SHEET).
    
    Calculates PER based on 4-quarter TTM EPS when available. Reports EPS basis, reporting
    period, and DER based on parent entity equity as well as total equity. Flags manual
    verification if quarters are non-contiguous, incomplete, or unusual.
    """
    metrics = {
        "eps": None,
        "eps_ttm": None,
        "eps_basis": None,
        "per": None,
        "per_quarterly": None,
        "der": None,
        "der_total_equity": None,
        "revenue": None,
        "net_income": None,
        "equity": None,
        "equity_parent": None,
        "revenue_growth_yoy": None,
        "net_income_growth_yoy": None,
        "reporting_period": None,
        "quarters_included": [],
        "needs_manual_verification": False,
        "verification_note": "",
    }
    if not fin_data:
        return metrics

    inc = fin_data.get("INCOME_STATEMENT", {})
    bal = fin_data.get("BALANCE_SHEET", {})

    inc_items = inc.get("items", [])
    bal_items = bal.get("items", [])

    def _get_item_eps(item_data: dict) -> float | None:
        raw_eps = item_data.get("laba_rugi_per_saham")
        if isinstance(raw_eps, (int, float)):
            return float(raw_eps)
        if isinstance(raw_eps, dict):
            parent_eps = raw_eps.get(
                "laba_per_saham_dasar_diatribusikan_kepada_pemilik_entitas_induk", {}
            )
            val = parent_eps.get("total")
            if not val or val == 0.0:
                val = parent_eps.get("laba_rugi_per_saham_dasar_dari_operasi_yang_dilanjutkan")
            if not val or val == 0.0:
                val = raw_eps.get("laba_rugi_per_saham_dasar_dari_operasi_yang_dilanjutkan")
            if val is not None:
                return float(val)
        return None

    if inc_items:
        latest_inc = inc_items[0].get("data", {})
        metrics["reporting_period"] = inc_items[0].get("label") or (
            f"Q{inc_items[0].get('quarter')} {inc_items[0].get('year')}"
            if inc_items[0].get("quarter") else "Kuartal Terakhir"
        )
        rev = latest_inc.get("penjualan_dan_pendapatan_usaha")
        net = latest_inc.get("laba_rugi")
        latest_eps = _get_item_eps(latest_inc)

        metrics["revenue"] = rev
        metrics["net_income"] = net
        metrics["eps"] = latest_eps

        # Collect TTM EPS from up to 4 quarters
        cum_eps_dict = {}
        for it in inc_items:
            year = str(it.get("year"))
            quarter = str(it.get("quarter"))
            q_eps = _get_item_eps(it.get("data", {}))
            if year and quarter and q_eps is not None:
                cum_eps_dict[(year, quarter)] = q_eps

        ttm_eps_list = []
        quarters_labels = []
        is_continuous = True
        
        for it in inc_items[:4]:
            year = str(it.get("year"))
            quarter = str(it.get("quarter"))
            lbl = it.get("label") or (
                f"Q{quarter} {year}"
                if quarter else "N/A"
            )
            
            if not year or not quarter or quarter == "None":
                is_continuous = False
                continue
                
            current_cum = cum_eps_dict.get((year, quarter))
            if current_cum is None:
                is_continuous = False
                continue
                
            if quarter == '1':
                standalone_eps = current_cum
            else:
                prev_quarter = str(int(quarter) - 1)
                prev_cum = cum_eps_dict.get((year, prev_quarter))
                if prev_cum is None:
                    is_continuous = False
                    continue
                standalone_eps = current_cum - prev_cum
                
            ttm_eps_list.append(standalone_eps)
            quarters_labels.append(lbl)

        if len(ttm_eps_list) == 4:
            metrics["eps_ttm"] = round(sum(ttm_eps_list), 2)
            metrics["quarters_included"] = quarters_labels
            metrics["eps_basis"] = f"TTM (Jumlah 4 Kuartal: {', '.join(quarters_labels)})"
            if not is_continuous:
                metrics["needs_manual_verification"] = True
                metrics["verification_note"] = "Data kuartal tidak kontinu (ada kuartal terlewat pada feed API), nilai TTM perlu verifikasi manual."
        elif ttm_eps_list or latest_eps is not None:
            if latest_eps is not None:
                metrics["eps_ttm"] = round(latest_eps * 4, 2)
                metrics["eps_basis"] = f"Annualized (Kuartal {metrics['reporting_period']} x 4)"
                metrics["needs_manual_verification"] = True
                if not is_continuous:
                    metrics["verification_note"] = "Data kuartal tidak kontinu (ada kuartal terlewat pada feed API), nilai TTM perlu verifikasi manual."
                else:
                    metrics["verification_note"] = f"Data hanya tersedia {len(ttm_eps_list)} kuartal, menggunakan estimasi disetahunkan (annualized)."

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
        eq_total = latest_bal.get("liabilitas_dan_ekuitas", {}).get("ekuitas", {}).get("total")
        eq_parent = latest_bal.get("liabilitas_dan_ekuitas", {}).get("ekuitas", {}).get(
            "ekuitas_yang_diatribusikan_kepada_pemilik_entitas_induk", {}
        ).get("total")

        metrics["equity"] = eq_total
        metrics["equity_parent"] = eq_parent

        if liab is not None:
            if eq_parent and eq_parent > 0:
                metrics["der"] = round(liab / eq_parent, 2)
            elif eq_total and eq_total > 0:
                metrics["der"] = round(liab / eq_total, 2)

            if eq_total and eq_total > 0:
                metrics["der_total_equity"] = round(liab / eq_total, 2)

    # Guard against zero, negative EPS, or extreme valuation (relative threshold: earnings yield < 0.5% or PER > 200x)
    PER_MAX_THRESHOLD = 200.0
    MIN_EARNINGS_YIELD = 0.005  # 0.5%, equivalent to PER > 200x
    active_eps = metrics["eps_ttm"] if metrics["eps_ttm"] is not None else (metrics["eps"] * 4 if metrics["eps"] else None)
    if active_eps is not None:
        if active_eps <= 0:
            metrics["per"] = "N/M"
        elif close_price:
            earnings_yield = active_eps / close_price
            calc_per = round(close_price / active_eps, 2)
            if earnings_yield < MIN_EARNINGS_YIELD or calc_per > PER_MAX_THRESHOLD:
                metrics["per"] = "N/M"
            else:
                metrics["per"] = calc_per
        else:
            metrics["per"] = "N/M" if active_eps < 0.1 else None

    if metrics["eps"] and close_price:
        if metrics["eps"] <= 0:
            metrics["per_quarterly"] = "N/M"
        else:
            calc_q_per = round(close_price / metrics["eps"], 2)
            metrics["per_quarterly"] = calc_q_per if calc_q_per <= (PER_MAX_THRESHOLD * 4) else "N/M"

    # Corporate action detection (e.g. DSSA stock split 1:25 in April 2026 unadjusted in 2025 financial statements)
    stock_code = fin_data.get("stock_code") or inc.get("stock_code") or bal.get("stock_code")
    if stock_code == "DSSA":
        SPLIT_RATIO = 25.0
        if metrics["eps_ttm"] is not None:
            raw_eps_ttm = metrics["eps_ttm"]
            metrics["raw_eps_ttm"] = raw_eps_ttm
            metrics["eps_ttm"] = round(raw_eps_ttm / SPLIT_RATIO, 2)
        if metrics["eps"] is not None:
            raw_eps = metrics["eps"]
            metrics["raw_eps"] = raw_eps
            metrics["eps"] = round(raw_eps / SPLIT_RATIO, 2)

        if metrics["eps_ttm"] and metrics["eps_ttm"] > 0 and close_price:
            metrics["per"] = round(close_price / metrics["eps_ttm"], 2)
            metrics["per_note"] = "(Disesuaikan Stock Split 1:25)"
        if metrics["eps"] and metrics["eps"] > 0 and close_price:
            metrics["per_quarterly"] = round(close_price / metrics["eps"], 2)

        basis_str = metrics.get("eps_basis") or ""
        metrics["eps_basis"] = f"{basis_str} (Disesuaikan Stock Split 1:25)"
        raw_ttm_str = f"Rp{metrics.get('raw_eps_ttm', 0):,.0f}" if metrics.get("raw_eps_ttm") else "-"
        raw_per_str = f"{round(close_price / metrics['raw_eps_ttm'], 2):,.2f}x" if (metrics.get("raw_eps_ttm") and close_price) else "-"
        metrics["needs_manual_verification"] = True
        metrics["verification_note"] = (
            f"Angka EPS TTM dan PER telah disesuaikan langsung dengan rasio aksi korporasi Stock Split 1:25 resmi "
            f"(efektif 9 April 2026) karena feed API masih menggunakan basis pra-split "
            f"(EPS TTM mentah pra-split: {raw_ttm_str}, PER mentah: {raw_per_str})."
        )

    # Staleness check: flag if reporting_period is > 3 quarters behind current quarter (default Q3 2026)
    rep_period = metrics.get("reporting_period", "")
    metrics["is_very_stale"] = False
    metrics["staleness_gap_quarters"] = 0
    if rep_period:
        q_match = re.search(r"Q([1-4])\s+(\d{4})", rep_period)
        if q_match:
            rep_q = int(q_match.group(1))
            rep_y = int(q_match.group(2))
            curr_y = 2026
            curr_q = 3
            quarter_diff = (curr_y * 4 + (curr_q - 1)) - (rep_y * 4 + (rep_q - 1))
            metrics["staleness_gap_quarters"] = quarter_diff
            if quarter_diff > 3:
                metrics["is_very_stale"] = True
                metrics["needs_manual_verification"] = True
                stale_msg = (
                    f"⚠️ Data Fundamental Sangat Basi: Laporan keuangan terakhir tercatat {rep_period} "
                    f"({quarter_diff} kuartal di belakang kuartal berjalan). "
                    f"Metrik valuasi & rasio keuangan tidak mencerminkan kondisi riil saat ini."
                )
                if metrics.get("verification_note"):
                    metrics["verification_note"] += f" | {stale_msg}"
                else:
                    metrics["verification_note"] = stale_msg

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
    personality_stats = extract_personality_wr_stats(analysis_text)
    if personality_stats.get("avg_wr") is not None:
        if candidate.wr_event is None:
            candidate.wr_event = personality_stats["avg_wr"]
    if personality_stats.get("is_weak_history"):
        wr_disp = candidate.wr_event if candidate.wr_event is not None else personality_stats["avg_wr"]
        candidate.wr_event_flag = f"{wr_disp:.1f}% ⚠️ Historis Lemah"
    elif candidate.wr_event is not None and candidate.wr_event < 50.0:
        candidate.wr_event_flag = f"{candidate.wr_event:.1f}% ⚠️ Historis Lemah"

    # Resolve stock name from analysis if needed
    if (not candidate.stock.name or candidate.stock.name == candidate.stock.code) and analysis_text:
        name_match = re.search(r'\n\s*_\s*([^\n_]+Tbk\.?|[^\n_]+)\s*_\s*\n', analysis_text)
        if name_match:
            candidate.stock.name = name_match.group(1).strip()

    # Detect AVOID status
    is_avoid = False
    avoid_reasons = []
    if re.search(r'\b(AVOID|HINDARI)\b', analysis_text, re.IGNORECASE):
        is_avoid = True
        avoid_reasons.append("Rekomendasi AVOID / HINDARI")
    score_match = re.search(r'Score:\s*\*{0,2}(\d+)/75\*{0,2}', analysis_text, re.IGNORECASE)
    if score_match and int(score_match.group(1)) <= 25:
        is_avoid = True
        avoid_reasons.append(f"Skor {score_match.group(1)}/75 (Tekanan Jual Kuat)")
    eff_wr = candidate.wr_event if candidate.wr_event is not None else personality_stats.get("avg_wr")
    if eff_wr is not None and eff_wr < 50.0:
        is_avoid = True
        avoid_reasons.append(f"WR Event {eff_wr:.1f}% (< 50%)")

    avoid_reason_str = ", ".join(avoid_reasons)

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
            is_avoid=is_avoid,
            avoid_reason=avoid_reason_str,
        )

    fin_metrics = fundamental_data or {}
    if "INCOME_STATEMENT" in fin_metrics or "BALANCE_SHEET" in fin_metrics or "CASH_FLOW_REPORT" in fin_metrics:
        close_px = latest.close if latest else 0.0
        fin_metrics = extract_fundamental_metrics(fin_metrics, close_price=close_px)

    expanded_analysis_text = expand_abbreviated_prices(analysis_text, ohlc_rows, pivot)

    return ValidationResult(
        stock=candidate.stock,
        analysis_text=expanded_analysis_text,
        broker_data=broker_data,
        foreign_flow_5d=foreign_flow_5d,
        pivot=pivot,
        trade_plan=trade_plan,
        fundamental_data=fin_metrics,
        fallback_reason=fallback_reason,
        personality_stats=personality_stats,
    )


def format_validation_summary(result: ValidationResult) -> str:
    lines = []
    lines.append(f"## {result.stock.code} - {result.stock.name}")
    lines.append(f"**Sector:** {result.stock.sector}")
    if result.sector_status_change_disclaimer:
        lines.append(f"ℹ️ {result.sector_status_change_disclaimer}")
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
        analysis_text = result.analysis_text
        if result.trade_plan:
            tp = result.trade_plan
            is_avoid_plan = tp.status.startswith("TIDAK DIREKOMENDASIKAN")
            if is_avoid_plan:
                analysis_text = re.sub(r"Stop\s*Loss:\s*Rp[^\n]+", f"Stop Loss (Pengaman Eksisting): Rp{tp.cutloss:,.0f}", analysis_text)
                analysis_text = re.sub(r"Entry:\s*Rp[^\n]+", f"Entry: TIDAK DISARANKAN ENTRY | Status: {tp.status}", analysis_text)
            else:
                analysis_text = re.sub(r"break\s*Rp[\d\.,]+[KMB]?", f"break Rp{tp.cutloss:,.0f}", analysis_text)
                analysis_text = re.sub(r"mantul/hold\s*Rp[\d\.,]+[KMB]?\s*-\s*Rp[\d\.,]+[KMB]?", f"mantul/hold Rp{tp.entry_low:,.0f}-Rp{tp.max_entry:,.0f}", analysis_text)
                analysis_text = re.sub(r"Entry:\s*Rp[^\n]+", f"Entry: Rp{tp.entry_low:,.0f} - Rp{tp.max_entry:,.0f} (Batas Max R:R 1.0:1) | Status: {tp.status}", analysis_text)
                analysis_text = re.sub(r"Target:\s*Rp[^\n]+", f"Target: Rp{tp.target1:,.0f} (T1) / Rp{tp.target2:,.0f} (T2)", analysis_text)
                analysis_text = re.sub(r"Stop\s*Loss:\s*Rp[^\n]+", f"Stop Loss: Rp{tp.cutloss:,.0f} (Proteksi Cutloss)", analysis_text)
            if "_Catatan: Seluruh level harga diselaraskan dengan Trade Plan" not in analysis_text:
                analysis_text += "\n  _Catatan: Seluruh level harga diselaraskan dengan Trade Plan resmi berbasis fraksi BEI (src/pivot.py)._"
        lines.append("### Analysis")
        lines.append(analysis_text)
        lines.append("")

    if result.fundamental_data:
        f = result.fundamental_data
        lines.append("### Fundamental & Valuasi")
        parts = []
        if f.get("reporting_period"):
            parts.append(f"Periode Laporan: {f['reporting_period']}")

        if f.get("eps_ttm") is not None:
            basis_str = f" ({f.get('eps_basis')})" if f.get("eps_basis") else ""
            if 0 < abs(f["eps_ttm"]) < 100:
                parts.append(f"EPS TTM: Rp{f['eps_ttm']:.2f}{basis_str}")
            else:
                parts.append(f"EPS TTM: Rp{f['eps_ttm']:,.0f}{basis_str}")

        if f.get("eps") is not None:
            eps_val = f["eps"]
            if 0 < abs(eps_val) < 100:
                parts.append(f"EPS: Rp{eps_val:.2f}")
            else:
                parts.append(f"EPS: Rp{eps_val:,.0f}")

        if f.get("per") is not None:
            lbl = "PER (TTM)" if f.get("eps_ttm") is not None else "PER"
            if f["per"] == "N/M":
                parts.append(f"{lbl}: N/M (Not Meaningful)")
            else:
                per_note = f" {f.get('per_note')}" if f.get("per_note") else ""
                parts.append(f"{lbl}: {f['per']}x{per_note}")
        if f.get("per_quarterly") is not None:
            parts.append(f"PER Kuartalan (Non-Annualized): {f['per_quarterly']}x (Harga / EPS Kuartal)")

        if f.get("der") is not None:
            parts.append(f"DER: {f['der']}x (Basis Ekuitas Induk)")
        if f.get("der_total_equity") is not None:
            parts.append(f"DER (Total Ekuitas): {f['der_total_equity']}x")

        if f.get("revenue_growth_yoy") is not None:
            parts.append(f"Pertumbuhan Pendapatan (YoY): {f['revenue_growth_yoy']:+,.1f}%")
        if f.get("net_income_growth_yoy") is not None:
            parts.append(f"Pertumbuhan Laba Bersih (YoY): {f['net_income_growth_yoy']:+,.1f}%")

        if f.get("is_very_stale"):
            gap = f.get('staleness_gap_quarters', 0)
            parts.append(
                f"⚠️ **Data Fundamental Sangat Basi**: Laporan keuangan terakhir tercatat {f.get('reporting_period')} "
                f"({gap} kuartal di belakang kuartal berjalan). "
                f"Metrik valuasi & rasio keuangan tidak mencerminkan kondisi riil saat ini."
            )
        if f.get("needs_manual_verification") and f.get("verification_note"):
            # If the verification_note is not just the staleness message, display it
            clean_note = f["verification_note"].replace(f"⚠️ Data Fundamental Sangat Basi: Laporan keuangan terakhir tercatat {f.get('reporting_period')} ({f.get('staleness_gap_quarters', 0)} kuartal di belakang kuartal berjalan). Metrik valuasi & rasio keuangan tidak mencerminkan kondisi riil saat ini.", "").strip(" |")
            if clean_note:
                parts.append(f"⚠️ **Perlu Verifikasi Manual**: {clean_note}")

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
        is_avoid_plan = tp.status.startswith("TIDAK DIREKOMENDASIKAN")
        lines.append("### Trade Plan (Fraksi BEI)")
        lines.append(f"  Status: **{tp.status}**")
        if is_avoid_plan:
            lines.append("  Entry Range: TIDAK DISARANKAN ENTRY")
            lines.append(f"  Batas Pengaman / Cutloss Eksisting: Rp{tp.cutloss:,.0f} (Level Support/Cutloss Pengaman)")
            lines.append(f"  Target Pantulan / Exit: Rp{tp.target1:,.0f} (T1) / Rp{tp.target2:,.0f} (T2)")
            lines.append(f"  ATR(14): Rp{tp.atr:,.2f}")
            if tp.warning:
                lines.append(f"  {tp.warning}")
        else:
            lines.append(f"  Entry Range: Rp{tp.entry_low:,.0f} - Rp{tp.entry_high:,.0f}")
            lines.append(f"  Batas Entry Maksimum (R:R 1.0:1): Rp{tp.max_entry:,.0f}")
            lines.append(f"  Cutloss: Rp{tp.cutloss:,.0f} (Proteksi di bawah Entry Range)")
            lines.append(f"  Target 1: Rp{tp.target1:,.0f} (Resisten Terdekat)")
            lines.append(f"  Target 2: Rp{tp.target2:,.0f} (Resisten Lanjutan)")
            mid_val = (tp.entry_low + tp.entry_high) / 2
            lines.append(f"  R:R Ratio (Midpoint Rp{mid_val:,.0f}): {tp.rr_ratio}:1")
            lines.append(f"  R:R Ratio (Batas Max Entry Rp{tp.max_entry:,.0f}): {tp.rr_at_max_entry}:1")
            lines.append(f"  ATR(14): Rp{tp.atr:,.2f}")
            if tp.warning:
                lines.append(f"  {tp.warning}")
            stop_pct = abs(tp.cutloss - mid_val) / mid_val * 100 if mid_val > 0 else 0.0
            lines.append(
                f"  _Catatan Statistik Edge vs Stop Loss: Potensi kenaikan (+7%) dan Drawdown (-3%) historis "
                f"diturunkan dari backtest event jangka pendek (D+2 s/d D+4) berbasis rata-rata ATR. Lebar stop loss "
                f"Trade Plan ini didasarkan pada batas teknikal/support (jarak cutloss ~{stop_pct:.1f}%), sehingga "
                f"statistik win rate historis tidak berlaku langsung untuk lebar stop loss Trade Plan tersebut._"
            )
        lines.append("")

    brokers = result.broker_data.get("brokers") if isinstance(result.broker_data, dict) else []
    lines.append("### Top Brokers & Aliran Dana")
    if brokers:
        for b in brokers[:5]:
            code = b.get("broker_code", "?")
            name = b.get("broker_name", "")
            nval = b.get("nval", 0)
            direction = "NET BUY" if nval > 0 else "NET SELL"
            lines.append(f"  {code} ({name}): {nval/1e9:+,.2f}B ({direction})")
        lines.append("")
        lines.append("  _Catatan Definisi Broker:_")
        lines.append("  - **Top Brokers (Tabel di atas)**: Netflow nominal murni sesi perdagangan harian terakhir (D-0).")
        lines.append("  - **Label Heavy Buyer/Seller (pada analisis di atas)**: Dihitung oleh algoritma idx-edge berbasis klasifikasi broker institusi/asing dan akumulasi rolling multi-hari (5D) untuk menyaring noise broker ritel lokal.")
    else:
        lines.append("  ℹ️ Data broker summary belum tersedia untuk sesi ini. Kemungkinan proses penarikan data berlangsung sebelum bursa selesai merekapitulasi data transaksi broker harian (End of Day / EOD).")
    lines.append("")

    return "\n".join(lines)
