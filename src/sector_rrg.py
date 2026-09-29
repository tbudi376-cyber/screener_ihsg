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
    return smoothed


def _ema(data: list[float], period: int) -> list[float]:
    if len(data) < period:
        return data[:]
    k = 2 / (period + 1)
    result = [sum(data[:period]) / period]
    for i in range(period, len(data)):
        result.append(data[i] * k + result[-1] * (1 - k))
    return result


OFFICIAL_IDX_SECTORS = {
    "Energy",
    "Basic Materials",
    "Industrials",
    "Consumer Non-Cyclicals",
    "Consumer Cyclicals",
    "Healthcare",
    "Financials",
    "Properties & Real Estate",
    "Technology",
    "Infrastructures",
    "Transportation & Logistic",
    "Transportation",
}


def classify_quadrant(rs_ratio: float, rs_momentum: float, tolerance: float = 0.0) -> str:
    """Classify RRG quadrant from RS-Ratio and RS-Momentum.
    
    Tolerance (e.g. 0.2) allows values near 100 to be recognized consistently
    across sectors where momentum values are tightly clustered around 100.
    """
    ratio_high = rs_ratio >= (100.0 - tolerance)
    mom_high = rs_momentum >= (100.0 - tolerance)
    if ratio_high and mom_high:
        return "Leading"
    if not ratio_high and mom_high:
        return "Improving"
    if ratio_high and not mom_high:
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
    tolerance: float = 0.2,
) -> list[tuple[str, str, float, float, float]]:
    """Rank sectors by attractiveness.

    Uses median aggregation across representative stocks per sector to prevent
    distortion by individual stock outliers (e.g. SMDR, ERAA). All 4 columns
    (Quadrant, Score, RS-Ratio, RS-Momentum) are derived from the exact same
    median aggregation using classify_quadrant(med_ratio, med_momentum, tolerance).
    Unknown or non-official sectors are strictly filtered out.

    Returns [(sector_name, quadrant, score, median_rs_ratio, median_rs_momentum), ...]
    sorted primarily by quadrant score (Leading=4.0, Improving=3.0, Weakening=2.0, Lagging=1.0)
    and secondarily by composite relative strength (RS-Ratio * RS-Momentum).
    """
    import statistics

    quadrant_score = {"Leading": 4.0, "Improving": 3.0, "Weakening": 2.0, "Lagging": 1.0}
    results = []
    for sector, points in sector_points.items():
        if not points:
            continue
        if sector == "Unknown" or sector not in OFFICIAL_IDX_SECTORS:
            continue

        ratios = [p.rs_ratio for p in points]
        moms = [p.rs_momentum for p in points]

        med_rs_ratio = round(statistics.median(ratios), 2)
        med_rs_momentum = round(statistics.median(moms), 2)

        quadrant = classify_quadrant(med_rs_ratio, med_rs_momentum, tolerance=tolerance)
        score = quadrant_score[quadrant]

        results.append((
            sector,
            quadrant,
            round(score, 2),
            med_rs_ratio,
            med_rs_momentum,
        ))

    # Sort primarily by quadrant score, secondarily by product of RS-Ratio * RS-Momentum
    results.sort(
        key=lambda x: (x[2], x[3] * x[4]),
        reverse=True,
    )
    return results


def select_representative_stocks(
    sector_config: dict[str, list[str]],
    sectors: list[str],
    min_stocks: int = 5,
) -> dict[str, list[str]]:
    """Select at least min_stocks representative stocks for each specified sector from config."""
    result = {}
    for s in sectors:
        stocks = sector_config.get(s, [])
        result[s] = stocks[: min(len(stocks), min_stocks)]
    return result
