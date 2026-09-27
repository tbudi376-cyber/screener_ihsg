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
        prev = ohlc_rows[i + 1]
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


def calculate_trade_plan(
    close: float,
    atr: float,
    support: float,
    pivot_levels: PivotLevels | None = None,
) -> TradePlan:
    """Calculate trade plan derived from actual price structure and pivot levels.

    Guarantees:
    - Cutloss is strictly below entry_low (cutloss < entry_low) for all candidates.
    - If ATR is smaller than the entry range width (close - entry_low), cutloss
      is adjusted based on S2 or swing level below entry_low with an ATR buffer.
    - Target 1 & 2 are derived from actual resistance levels (R1, R2, R3).
    - R:R ratio varies dynamically according to each stock's technical structure.
    """
    entry_high = close
    entry_low = support if (support and support < close) else (close - 0.5 * atr)

    # 1. Determine Cutloss: Must be strictly below entry_low
    buffer = max(0.5 * atr, 1.0)

    # Candidate cutloss from ATR subtraction from close
    atr_cutloss = close - 1.0 * atr

    if pivot_levels and pivot_levels.s2 < entry_low:
        # If S2 is available below entry_low, use S2 or entry_low minus buffer
        candidate_cl = min(entry_low - buffer, pivot_levels.s2)
    elif atr_cutloss < entry_low:
        candidate_cl = atr_cutloss
    else:
        # ATR is too small relative to entry range width; anchor below entry_low
        candidate_cl = entry_low - buffer

    cutloss = round(candidate_cl, 0)
    # Strict safety invariant: cutloss MUST be strictly lower than entry_low
    if cutloss >= entry_low:
        cutloss = round(entry_low - buffer, 0)

    # 2. Determine Targets from Pivot Resistance (R1, R2, R3)
    if pivot_levels:
        # If R1 is sufficiently above close (> 0.4x ATR), use R1 as Target 1
        if pivot_levels.r1 >= close + 0.4 * atr:
            target1 = pivot_levels.r1
            target2 = pivot_levels.r2 if pivot_levels.r2 > target1 else (target1 + 1.0 * atr)
        else:
            # If price is already near or above R1, aim for R2 as Target 1 and R3 as Target 2
            target1 = pivot_levels.r2 if pivot_levels.r2 > close else (close + 1.5 * atr)
            target2 = pivot_levels.r3 if pivot_levels.r3 > target1 else (target1 + 1.0 * atr)
    else:
        target1 = close + 1.5 * atr
        target2 = close + 2.5 * atr

    # Sanity check: targets must be above entry_high
    target1 = round(max(target1, close + 0.5 * atr), 0)
    target2 = round(max(target2, target1 + 0.5 * atr), 0)

    # 3. Dynamic R:R ratio based on actual price structure
    # Calculated from the midpoint of the entry range (realistic accumulation cost)
    entry_mid = (entry_low + entry_high) / 2
    risk = entry_mid - cutloss
    reward = target1 - entry_mid
    rr_ratio = round(reward / risk, 2) if risk > 0 else 0.0

    return TradePlan(
        entry_low=round(entry_low, 0),
        entry_high=round(entry_high, 0),
        cutloss=cutloss,
        target1=target1,
        target2=target2,
        rr_ratio=rr_ratio,
        atr=round(atr, 2),
    )
