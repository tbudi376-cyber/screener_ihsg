from dataclasses import dataclass, field


@dataclass
class Stock:
    code: str
    name: str
    sector: str


@dataclass
class OHLCRow:
    date: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    value: float
    f_buy: float = 0.0
    f_sell: float = 0.0
    n_foreign: float = 0.0


@dataclass
class PivotLevels:
    pivot: float
    r1: float
    r2: float
    r3: float
    s1: float
    s2: float
    s3: float


@dataclass
class RRGPoint:
    code: str
    rs_ratio: float
    rs_momentum: float
    quadrant: str


@dataclass
class TradePlan:
    entry_low: float
    entry_high: float
    cutloss: float
    target1: float
    target2: float
    rr_ratio: float
    atr: float
    warning: str = ""


@dataclass
class Candidate:
    stock: Stock
    bucket: str
    summary: str
    wr_event: float | None = None
    potential: float | None = None
    drawdown: float | None = None
    note: str = ""
    wr_event_flag: str | None = None


@dataclass
class ValidationResult:
    stock: Stock
    analysis_text: str
    broker_data: dict = field(default_factory=dict)
    foreign_flow_5d: list = field(default_factory=list)
    pivot: PivotLevels | None = None
    trade_plan: TradePlan | None = None
    fundamental_data: dict = field(default_factory=dict)
    fallback_reason: str = ""
    personality_stats: dict = field(default_factory=dict)


@dataclass
class QuotaUsageBreakdown:
    screener_calls: int = 1
    benchmark_calls: int = 1
    rrg_sector_calls: int = 0
    rrg_sectors_processed: int = 0
    rrg_stocks_processed: int = 0
    validation_calls: int = 0
    validation_stocks_processed: int = 0
    total_calls: int = 0
    details: list[str] = field(default_factory=list)
