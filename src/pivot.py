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
