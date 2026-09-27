from datetime import datetime
from pathlib import Path
from src.models import Candidate, ValidationResult
from src.validator import format_validation_summary


def generate_daily_report(
    date: str,
    sector_ranking: list[tuple],
    candidates: list[Candidate],
    validations: list[ValidationResult],
    quota_used: int,
) -> str:
    lines = []
    lines.append(f"# Screener IHSG - Laporan Harian {date}")
    lines.append(f"_Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}_")
    lines.append(f"_Kuota API terpakai: {quota_used} request_")
    lines.append("")
    lines.append("---")
    lines.append("")

    lines.append("## 1. Ranking Sektor (RRG)")
    if sector_ranking:
        lines.append("")
        lines.append("| Rank | Sektor | Kuadran | Skor |")
        lines.append("|------|--------|---------|------|")
        for i, (sector, quadrant, score) in enumerate(sector_ranking, 1):
            lines.append(f"| {i} | {sector} | {quadrant} | {score} |")
    else:
        lines.append("Tidak ada data RRG tersedia.")
    lines.append("")

    lines.append("## 2. Kandidat Screening")
    if candidates:
        lines.append("")
        lines.append("| # | Kode | Nama | Sektor | Sinyal | WR Event | Potensi | DD |")
        lines.append("|---|------|------|--------|--------|----------|---------|-----|")
        for i, c in enumerate(candidates, 1):
            wr = f"{c.wr_event:.1f}%" if c.wr_event else "-"
            pot = f"+{c.potential:.0f}%" if c.potential else "-"
            dd = f"{c.drawdown:.0f}%" if c.drawdown else "-"
            lines.append(
                f"| {i} | {c.stock.code} | {c.stock.name} | "
                f"{c.stock.sector} | {c.bucket} | {wr} | {pot} | {dd} |"
            )
    else:
        lines.append("Tidak ada kandidat yang lolos filter hari ini.")
    lines.append("")

    lines.append("## 3. Validasi Mendalam")
    if validations:
        for v in validations:
            lines.append("")
            lines.append(format_validation_summary(v))
    else:
        lines.append("Tidak ada validasi (tidak ada kandidat).")
    lines.append("")

    lines.append("---")
    lines.append("_Disclaimer: Analisa ini berbasis data historis dan pola statistik.")
    lines.append("Bukan ajakan jual/beli. Keputusan investasi tanggung jawab masing-masing._")

    return "\n".join(lines)


def save_report(content: str, output_dir: str) -> str:
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    date_str = datetime.now().strftime("%Y-%m-%d")
    filename = f"screener_{date_str}.md"
    filepath = out_path / filename
    filepath.write_text(content, encoding="utf-8")
    return str(filepath)
