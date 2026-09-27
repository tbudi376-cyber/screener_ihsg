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
