import re
from src.models import Candidate, Stock, OHLCRow


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


def screen_mandiri_constituents(
    favored_sectors: list[str],
    sector_config: dict[str, list[str]],
    stock_ohlc_map: dict[str, list[OHLCRow]],
    min_value: float = 1_000_000_000.0,
    max_results: int = 5,
) -> list[Candidate]:
    """Filter sector constituents according to PRD §6 & §7.3 philosophy:
    - Sektor kuadran Leading & Improving (favored_sectors)
    - val >= 1mil: value transaksi harian >= Rp1 Miliar (Hard Filter)
    - high > low: gugurkan saham yang terkunci batas auto rejection (Hard Filter)
    - close >= sma20: harga penutupan di atas atau sama dengan SMA20 (Hard Filter Tren)
    - vol > ma20vol: volume harian > MA20 volume
    - nbsa > 0: Net Foreign Buy harian > 0 (n_foreign > 0 atau f_buy > f_sell)
    """
    candidates_with_score = []

    for sector in favored_sectors:
        codes = sector_config.get(sector, [])
        for code in codes:
            rows = stock_ohlc_map.get(code)
            if not rows or len(rows) < 20:
                continue

            latest = rows[-1]
            # Syarat 1 (Hard Filter): Nilai transaksi harian >= Rp 1 Miliar
            if latest.value < min_value:
                continue

            # Syarat 2 (Hard Filter): Gugurkan saham terkunci batas auto rejection (High == Low)
            if latest.high <= latest.low:
                continue

            sma20_vol = sum(r.volume for r in rows[-20:]) / 20.0
            sma20_close = sum(r.close for r in rows[-20:]) / 20.0

            # Syarat 3 (Hard Filter Tren Wajib): Harga penutupan di atas atau sama dengan SMA20
            # Mencegah masuknya saham downtrend / falling knives (e.g. GOTO, TMAS)
            if latest.close < sma20_close:
                continue

            # Syarat kelonggaran 3/4 HANYA berlaku untuk volume harian atau net buy asing:
            c_vol = (latest.volume > sma20_vol) if sma20_vol > 0 else False
            c_nbsa = (latest.n_foreign > 0) or (latest.f_buy > latest.f_sell)

            vol_ratio = (latest.volume / sma20_vol) if sma20_vol > 0 else 1.0
            pct_above_ma = ((latest.close - sma20_close) / sma20_close * 100) if sma20_close > 0 else 0.0

            if c_vol and c_nbsa:
                bucket = "🟢 SINYAL MANDIRI (PRD §6)"
                note = "Lolos 4/4 filter PRD (Val > 1M, Vol > MA20, NBSA > 0, Close >= SMA20)"
                score = 100.0 + vol_ratio * 5.0 + (10.0 if latest.n_foreign > 0 else 0.0)
            elif c_vol or c_nbsa:
                bucket = "🥷 AKUMULASI MANDIRI (PRD §6)"
                missed = []
                if not c_vol:
                    missed.append("Vol <= MA20")
                if not c_nbsa:
                    missed.append("NBSA <= 0")
                note = f"Lolos 3/4 filter PRD ({', '.join(missed)}, Tren di atas SMA20)"
                score = 50.0 + vol_ratio * 3.0 + (5.0 if latest.n_foreign > 0 else 0.0)
            else:
                continue

            summary = (
                f"Top-Down Sektor {sector} | Val Rp{latest.value/1e9:.2f}B | "
                f"Vol {vol_ratio:.1f}x MA20 | NBSA {latest.n_foreign:+,.0f} shs | "
                f"Close Rp{latest.close:,.0f} ({pct_above_ma:+.1f}% vs MA20)"
            )

            cand = Candidate(
                stock=Stock(code=code, name=code, sector=sector),
                bucket=bucket,
                summary=summary,
                wr_event=None,
                potential=None,
                drawdown=None,
                note=note,
            )
            candidates_with_score.append((cand, score))

    candidates_with_score.sort(key=lambda x: x[1], reverse=True)
    return [item[0] for item in candidates_with_score[:max_results]]

