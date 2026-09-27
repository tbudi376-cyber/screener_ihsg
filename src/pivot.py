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
) -> TradePlan:
    """Calculate trade plan derived from actual price structure and pivot levels.

    Guarantees:
    - All output prices (entry_low, entry_high, cutloss, target1, target2) are
      rounded to official IDX price tick fractions (Kep-00023/BEI/03-2020).
    - Cutloss is strictly below entry_low (cutloss < entry_low) for all candidates.
    - If ATR is smaller than the entry range width (close - entry_low), cutloss
      is adjusted based on S2 or swing level below entry_low with an ATR buffer.
    - Target 1 & 2 are derived from actual resistance levels (R1, R2, R3).
    - R:R ratio varies dynamically according to each stock's technical structure.
    """
    raw_entry_high = close
    raw_entry_low = support if (support and support < close) else (close - 0.5 * atr)

    entry_high = round_to_idx_tick(raw_entry_high)
    entry_low = round_to_idx_tick(raw_entry_low)
    if entry_low >= entry_high:
        entry_low = entry_high - get_idx_tick_size(entry_high)

    # 1. Determine Cutloss: Primary rule is Close - 1.0 * ATR
    # Fallback to S2 or buffer only if Close - ATR falls inside or above entry_low
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

    # 3. Dynamic R:R ratio based on actual price structure
    entry_mid = (entry_low + entry_high) / 2
    risk = entry_mid - cutloss
    reward = target1 - entry_mid
    rr_ratio = round(reward / risk, 2) if risk > 0 else 0.0

    warning = ""
    if rr_ratio < 1.0:
        warning = (
            f"⚠️ PERINGATAN R:R < 1.0 ({rr_ratio:.2f}:1): Potensi risiko lebih besar daripada "
            f"reward ke Target 1 jika entry di harga rata-rata/mid (Rp{entry_mid:,.0f}). Disarankan menunggu "
            f"pelemahan (buy on weakness) mendekati batas bawah Rp{entry_low:,.0f} untuk memperbaiki rasio risk-to-reward."
        )

    return TradePlan(
        entry_low=entry_low,
        entry_high=entry_high,
        cutloss=cutloss,
        target1=target1,
        target2=target2,
        rr_ratio=rr_ratio,
        atr=round(atr, 2),
        warning=warning,
    )
