from src.models import PivotLevels, OHLCRow, TradePlan


def get_idx_tick_size(price: float) -> int:
    """Return the official IDX (Bursa Efek Indonesia) tick size for a given price level.

    BEI Price Fractions (Keputusan Direksi PT BEI Nomor Kep-00023/BEI/03-2020):
    - < Rp200: kelipatan Rp1
    - Rp200 s/d < Rp500: kelipatan Rp2
    - Rp500 s/d < Rp2.000: kelipatan Rp5
    - Rp2.000 s/d < Rp5.000: kelipatan Rp10
    - >= Rp5.000: kelipatan Rp25
    """
    if price < 200:
        return 1
    elif price < 500:
        return 2
    elif price < 2000:
        return 5
    elif price < 5000:
        return 10
    else:
        return 25


def round_to_idx_tick(price: float) -> int:
    """Round a price to the nearest official IDX price fraction (tick size)."""
    if price <= 0:
        return 0
    tick = get_idx_tick_size(price)
    return int(round(price / tick) * tick)


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
    """Calculate Average True Range (ATR) over period candles.

    Official system convention: ohlc_rows is ordered oldest-to-newest.
    ohlc_rows[0] is the oldest candle, ohlc_rows[-1] is the most recent candle.
    """
    if len(ohlc_rows) < 2:
        raise ValueError(f"Need at least 2 rows for ATR, got {len(ohlc_rows)}")

    true_ranges = []
    for i in range(1, len(ohlc_rows)):
        current = ohlc_rows[i]
        prev = ohlc_rows[i - 1]
        tr = max(
            current.high - current.low,
            abs(current.high - prev.close),
            abs(current.low - prev.close),
        )
        true_ranges.append(tr)

    use = true_ranges[-period:]
    if not use:
        raise ValueError("Not enough data to calculate ATR")
    return sum(use) / len(use)


def calculate_trade_plan(
    close: float,
    atr: float,
    support: float,
    pivot_levels: PivotLevels | None = None,
    min_rr: float = 1.0,
) -> TradePlan:
    """Calculate trade plan derived from actual price structure and pivot levels.

    Guarantees:
    - All output prices (entry_low, entry_high, cutloss, target1, target2, max_entry)
      are rounded to official IDX price tick fractions (Kep-00023/BEI/03-2020).
    - Entry Range is preserved naturally from price structure without artificial narrowing.
    - Maximum Entry is calculated via formula: E <= (T1 + k*Cutloss) / (1 + k).
    - If close > max_entry, issues status 'TUNGGU (Buy on Weakness)' with max_entry level.
    - If max_entry < entry_low, issues status 'PLAN TIDAK VALID'.
    - Displays R:R both at midpoint and at maximum entry boundary.
    """
    raw_entry_high = close
    raw_entry_low = support if (support and support < close) else (close - 0.5 * atr)

    entry_high = round_to_idx_tick(raw_entry_high)
    entry_low = round_to_idx_tick(raw_entry_low)
    if entry_low >= entry_high:
        entry_low = entry_high - get_idx_tick_size(entry_high)

    # 1. Determine Cutloss: Primary rule is Close - 1.0 * ATR
    atr_cutloss = close - 1.0 * atr
    buffer = max(0.5 * atr, 1.0)

    if atr_cutloss < entry_low:
        candidate_cl = atr_cutloss
    elif pivot_levels and pivot_levels.s2 < entry_low:
        candidate_cl = pivot_levels.s2
    else:
        candidate_cl = entry_low - buffer

    cutloss = round_to_idx_tick(candidate_cl)
    # Strict safety invariant: cutloss MUST be strictly lower than entry_low
    if cutloss >= entry_low:
        cutloss = entry_low - get_idx_tick_size(entry_low)

    # 2. Determine Targets from Pivot Resistance (R1, R2, R3)
    if pivot_levels:
        if pivot_levels.r1 >= close + 0.4 * atr:
            raw_t1 = pivot_levels.r1
            raw_t2 = pivot_levels.r2 if pivot_levels.r2 > raw_t1 else (raw_t1 + 1.0 * atr)
        else:
            raw_t1 = pivot_levels.r2 if pivot_levels.r2 > close else (close + 1.5 * atr)
            raw_t2 = pivot_levels.r3 if pivot_levels.r3 > raw_t1 else (raw_t1 + 1.0 * atr)
    else:
        raw_t1 = close + 1.5 * atr
        raw_t2 = close + 2.5 * atr

    target1 = round_to_idx_tick(raw_t1)
    if target1 <= entry_high:
        target1 = entry_high + get_idx_tick_size(entry_high)

    target2 = round_to_idx_tick(raw_t2)
    if target2 <= target1:
        target2 = target1 + get_idx_tick_size(target1)

    # 3. Calculate Maximum Entry price based on required minimum R:R (k)
    # Formula: E <= (T1 + k * Cutloss) / (1 + k)
    raw_max_entry = (target1 + min_rr * cutloss) / (1.0 + min_rr)
    max_entry = round_to_idx_tick(raw_max_entry)
    # Ensure max_entry strictly satisfies <= raw_max_entry to maintain minimum R:R
    if max_entry > raw_max_entry:
        max_entry -= get_idx_tick_size(max_entry)

    # R:R at midpoint
    entry_mid = (entry_low + entry_high) / 2
    risk_mid = entry_mid - cutloss
    reward_mid = target1 - entry_mid
    rr_ratio = round(reward_mid / risk_mid, 2) if risk_mid > 0 else 0.0

    # R:R at max_entry boundary
    risk_max = max_entry - cutloss
    reward_max = target1 - max_entry
    rr_at_max = round(reward_max / risk_max, 2) if risk_max > 0 else 0.0

    # 4. Status and Advisory Warnings
    if max_entry < entry_low:
        status = "PLAN TIDAK VALID"
        warning = (
            f"⛔ PLAN TIDAK VALID: Level entry maksimum untuk R:R {min_rr}:1 (Rp{max_entry:,.0f}) "
            f"berada di bawah batas bawah entry (Rp{entry_low:,.0f}). Tidak disarankan entry karena "
            f"potensi reward tidak sebanding dengan lebar stop loss struktur harga."
        )
    elif close > max_entry:
        status = "TUNGGU (Buy on Weakness)"
        risk_at_price = close - cutloss
        reward_at_price = target1 - close
        rr_at_price = round(reward_at_price / risk_at_price, 2) if risk_at_price > 0 else 0.0
        rr_warn = " — PERINGATAN R:R < 1.0" if (rr_at_price < 1.0 or rr_ratio < 1.0) else ""
        warning = (
            f"⏳ TUNGGU (Buy on Weakness){rr_warn}: Harga saat ini (Rp{close:,.0f}) berada di atas batas entry maksimum "
            f"(Rp{max_entry:,.0f}) untuk R:R {min_rr}:1. "
            f"R:R jika entry di harga sekarang (Rp{close:,.0f}): {rr_at_price:.2f}:1. "
            f"R:R jika entry di midpoint range (Rp{entry_mid:,.0f}): {rr_ratio:.2f}:1. "
            f"Disarankan menunggu pelemahan di area Rp{entry_low:,.0f} s/d Rp{max_entry:,.0f} "
            f"agar rasio risk-to-reward minimal {min_rr}:1 tercapai."
        )
    elif rr_ratio < 1.0:
        status = "VALID"
        warning = (
            f"⚠️ PERINGATAN R:R < 1.0 ({rr_ratio:.2f}:1): Potensi risiko lebih besar daripada "
            f"reward ke Target 1 jika entry di harga rata-rata/mid (Rp{entry_mid:,.0f})."
        )
    else:
        status = "VALID"
        warning = ""

    return TradePlan(
        entry_low=entry_low,
        entry_high=entry_high,
        cutloss=cutloss,
        target1=target1,
        target2=target2,
        rr_ratio=rr_ratio,
        atr=round(atr, 2),
        warning=warning,
        max_entry=max_entry,
        rr_at_max_entry=rr_at_max,
        status=status,
    )
