import re
from src.models import Candidate, Stock


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
