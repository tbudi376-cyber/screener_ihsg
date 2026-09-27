import json
from dataclasses import dataclass
from pathlib import Path
from src.models import OHLCRow


@dataclass
class McpCallRequest:
    """Represents a call to be made via the MCP idx-edge server.
    The agent executor translates these into actual call_mcp_tool invocations."""
    tool_name: str
    arguments: dict


class McpClient:
    """Wrapper for idx-edge MCP tool calls.

    In v1, this class produces McpCallRequest objects that the orchestrating
    agent executes. It tracks quota usage and caches results within a session.
    """

    def __init__(self):
        self._cache: dict[str, any] = {}
        self._quota_used = 0

    def quota_used(self) -> int:
        return self._quota_used

    def _cache_key(self, tool: str, **kwargs) -> str:
        return f"{tool}:{json.dumps(kwargs, sort_keys=True)}"

    def _record_call(self, quota_cost: int = 1):
        self._quota_used += quota_cost

    def get_screener_request(self) -> McpCallRequest:
        return McpCallRequest(
            tool_name="screener_saham_terkini",
            arguments={},
        )

    def get_price_history_request(
        self, code: str, limit: int = 120, frame: str = "daily",
        fields: str | None = None,
    ) -> McpCallRequest:
        args = {"code": code, "limit": limit, "frame": frame}
        if fields:
            args["fields"] = fields
        return McpCallRequest(tool_name="riwayat_harga", arguments=args)

    def get_broker_summary_request(
        self, code: str, flow: str = "all", broker_limit: int = 10,
    ) -> McpCallRequest:
        return McpCallRequest(
            tool_name="broker_summary",
            arguments={"code": code, "flow": flow, "broker_limit": broker_limit},
        )

    def get_accumulation_request(
        self, code: str, start_date: str | None = None, end_date: str | None = None,
        top: int = 3,
    ) -> McpCallRequest:
        args = {"code": code, "top": top}
        if start_date:
            args["start_date"] = start_date
        if end_date:
            args["end_date"] = end_date
        return McpCallRequest(tool_name="akumulasi_broker_historis", arguments=args)

    def get_analysis_request(self, code: str) -> McpCallRequest:
        return McpCallRequest(tool_name="analisa_saham", arguments={"code": code})

    def get_analysis_batch_request(self, codes: list[str]) -> McpCallRequest:
        return McpCallRequest(
            tool_name="analisa_batch",
            arguments={"codes": ",".join(codes[:5])},
        )

    def get_financial_report_request(
        self, code: str, report_type: str = "all", period: str = "quarterly",
        limit: int = 4,
    ) -> McpCallRequest:
        return McpCallRequest(
            tool_name="laporan_keuangan",
            arguments={
                "code": code, "report_type": report_type,
                "period": period, "limit": limit,
            },
        )

    def get_price_batch_request(self, codes: list[str]) -> McpCallRequest:
        return McpCallRequest(
            tool_name="harga_batch",
            arguments={"codes": ",".join(codes[:20])},
        )

    @staticmethod
    def parse_ohlc_rows(api_rows: list[dict]) -> list[OHLCRow]:
        """Parse raw API rows and sort ascending by date (oldest-to-newest).

        The idx-edge API returns newest-first rows. This parser guarantees
        that the resulting list is sorted in strict chronological order
        (oldest-to-newest: ohlc_rows[0] is oldest, ohlc_rows[-1] is newest),
        which is the single official convention across the entire codebase.
        """
        rows = [
            OHLCRow(
                date=r.get("date", ""),
                open=float(r.get("open", 0)),
                high=float(r.get("high", 0)),
                low=float(r.get("low", 0)),
                close=float(r.get("close", 0)),
                volume=float(r.get("volume", 0)),
                value=float(r.get("value", 0)),
                f_buy=float(r.get("f_buy", 0)),
                f_sell=float(r.get("f_sell", 0)),
                n_foreign=float(r.get("n_foreign", 0)),
            )
            for r in api_rows
        ]
        rows.sort(key=lambda r: r.date)
        return rows


def extract_closes(ohlc_rows: list[OHLCRow]) -> list[float]:
    """Extract closing prices from an OHLCRow series in chronological order."""
    return [r.close for r in ohlc_rows]


def load_sector_config() -> dict[str, list[str]]:
    path = Path(__file__).parent.parent / "config" / "sectors.json"
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def get_stocks_for_sector(sector: str) -> list[str]:
    config = load_sector_config()
    return config.get(sector, [])
