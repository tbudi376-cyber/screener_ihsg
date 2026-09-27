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
            arguments={"code": code, "report_type": "all", "period": "quarterly", "limit": 4},
        ),
    ]


def parse_foreign_flow_5d(ohlc_rows: list[OHLCRow]) -> list[float]:
    return [row.n_foreign for row in ohlc_rows[:5]]


def assemble_validation(
    candidate: Candidate,
    analysis_text: str,
    broker_data: dict,
    ohlc_rows: list[OHLCRow],
) -> ValidationResult:
    latest = ohlc_rows[0] if ohlc_rows else None
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
        )

    return ValidationResult(
        stock=candidate.stock,
        analysis_text=analysis_text,
        broker_data=broker_data,
        foreign_flow_5d=foreign_flow_5d,
        pivot=pivot,
        trade_plan=trade_plan,
    )


def format_validation_summary(result: ValidationResult) -> str:
    lines = []
    lines.append(f"## {result.stock.code} - {result.stock.name}")
    lines.append(f"**Sector:** {result.stock.sector}")
    lines.append("")

    lines.append("### Analysis")
    lines.append(result.analysis_text)
    lines.append("")

    lines.append("### Net Foreign Flow (5D)")
    if result.foreign_flow_5d:
        for i, flow in enumerate(result.foreign_flow_5d):
            direction = "BUY" if flow > 0 else "SELL"
            lines.append(f"  D-{i}: {flow:+,.0f} shares ({direction})")
    else:
        lines.append("  No data available")
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
        lines.append("### Trade Plan")
        lines.append(f"  Entry Range: {tp.entry_low:,.0f} - {tp.entry_high:,.0f}")
        lines.append(f"  Cutloss: {tp.cutloss:,.0f} (1x ATR)")
        lines.append(f"  Target 1: {tp.target1:,.0f} (1.5x ATR)")
        lines.append(f"  Target 2: {tp.target2:,.0f} (2x ATR)")
        lines.append(f"  R:R Ratio: {tp.rr_ratio}:1")
        lines.append(f"  ATR(14): {tp.atr:,.2f}")
        lines.append("")

    if result.broker_data.get("brokers"):
        lines.append("### Top Brokers")
        for b in result.broker_data["brokers"][:5]:
            code = b.get("broker_code", "?")
            name = b.get("broker_name", "")
            nval = b.get("nval", 0)
            direction = "NET BUY" if nval > 0 else "NET SELL"
            lines.append(f"  {code} ({name}): {nval/1e9:+,.2f}B ({direction})")
        lines.append("")

    return "\n".join(lines)
