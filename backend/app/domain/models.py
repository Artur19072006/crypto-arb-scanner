from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


LiquidityStatus = Literal["OK", "Thin", "Holey"]
DepthStatus = Literal["OK", "Thin", "Insufficient", "Unknown"]
FundingImpact = Literal["Good", "Neutral", "Bad"]
DataSourceMode = Literal["mock", "live"]
SymbolSelectionMode = Literal["manual", "auto"]
OpportunitySortBy = Literal[
    "raw_spread",
    "net_spread",
    "volume_24h",
    "symbol",
    "updated_at",
]
SortDirection = Literal["asc", "desc"]


class MarketSnapshot(BaseModel):
    exchange: str
    symbol: str
    best_bid: float = Field(gt=0)
    best_bid_size: float = Field(ge=0)
    best_ask: float = Field(gt=0)
    best_ask_size: float = Field(ge=0)
    volume_24h_usd: float = Field(ge=0)
    funding_rate_percent: float
    next_funding_time: datetime | None
    timestamp: datetime


class MarketSymbol(BaseModel):
    exchange: str
    symbol: str
    volume_24h_usd: float = Field(ge=0)


class OrderBookLevel(BaseModel):
    price: float = Field(gt=0)
    quantity: float = Field(gt=0)


class OrderBookSnapshot(BaseModel):
    exchange: str
    symbol: str
    bids: list[OrderBookLevel]
    asks: list[OrderBookLevel]
    timestamp: datetime


class DepthCheckResult(BaseModel):
    target_notional_usd: float = Field(gt=0)
    can_fill_long: bool
    can_fill_short: bool
    long_effective_price: float | None = Field(default=None, gt=0)
    short_effective_price: float | None = Field(default=None, gt=0)
    long_slippage_percent: float | None = None
    short_slippage_percent: float | None = None
    depth_adjusted_raw_spread_percent: float | None = None
    depth_adjusted_net_spread_percent: float | None = None
    depth_status: DepthStatus
    depth_reasons: list[str] = Field(default_factory=list)


class ExchangeFees(BaseModel):
    maker_percent: float = Field(ge=0)
    taker_percent: float = Field(ge=0)


class ArbitrageOpportunity(BaseModel):
    symbol: str
    long_exchange: str
    short_exchange: str
    ask_price: float = Field(gt=0)
    bid_price: float = Field(gt=0)
    raw_spread_percent: float
    estimated_net_spread_percent: float
    estimated_fee_percent: float = Field(default=0, ge=0)
    volume_24h_usd: float = Field(ge=0)
    best_ask_size: float = Field(ge=0)
    best_bid_size: float = Field(ge=0)
    long_funding_rate_percent: float
    short_funding_rate_percent: float
    funding_rate_difference_percent: float
    next_funding_time: datetime | None
    funding_impact: FundingImpact
    liquidity_status: LiquidityStatus
    depth_check: DepthCheckResult | None = None
    timestamp: datetime


class ScannerFilters(BaseModel):
    min_raw_spread: float | None = Field(default=None, ge=0)
    min_net_spread: float | None = None
    min_volume_24h_usd: float | None = Field(default=None, ge=0)
    exchanges: tuple[str, ...] = ()


class OpportunitiesResponse(BaseModel):
    opportunities: list[ArbitrageOpportunity]
    total_stored_opportunity_count: int = Field(ge=0)
    filtered_opportunity_count: int = Field(ge=0)
    returned_count: int = Field(ge=0)
    sort_by: OpportunitySortBy
    sort_dir: SortDirection
    limit: int = Field(ge=1)


class TelegramDisplaySettings(BaseModel):
    enabled: bool = False
    alert_cooldown_seconds: int = Field(default=300, ge=0)


class SymbolSelectionConfig(BaseModel):
    mode: SymbolSelectionMode = "manual"
    min_volume_24h_usd: float | None = Field(default=None, ge=0)
    max_volume_24h_usd: float | None = Field(default=None, ge=0)
    max_symbols: int = Field(default=10, ge=1)
    min_exchanges_required: int = Field(default=2, ge=2)
    include_symbols: tuple[str, ...] = ()
    exclude_symbols: tuple[str, ...] = ()


class SymbolUniverseSelection(BaseModel):
    mode: SymbolSelectionMode = "manual"
    symbols: tuple[str, ...] = ()
    symbols_by_connector: dict[str, tuple[str, ...]] = Field(default_factory=dict)
    min_volume_24h_usd: float | None = None
    max_volume_24h_usd: float | None = None
    symbols_on_2_exchanges: int = Field(default=0, ge=0)
    symbols_on_3_exchanges: int = Field(default=0, ge=0)
    errors: tuple[str, ...] = ()


class DepthCheckConfig(BaseModel):
    enabled: bool = False
    target_notional_usd: float = Field(default=1000, gt=0)
    max_opportunities_to_check: int = Field(default=10, ge=1)
    order_book_limit: int = Field(default=50, ge=1)
    max_allowed_slippage_percent: float = Field(default=0.3, ge=0)


class AppConfig(BaseModel):
    data_source_mode: DataSourceMode = "mock"
    enabled_connectors: tuple[str, ...] = ("fake",)
    max_symbols: int = Field(default=10, ge=1)
    symbol_allowlist: tuple[str, ...] = ()
    symbol_selection: SymbolSelectionConfig = Field(
        default_factory=SymbolSelectionConfig
    )
    fees: dict[str, ExchangeFees]
    default_filters: ScannerFilters
    supported_exchanges: tuple[str, ...]
    depth_check: DepthCheckConfig = Field(default_factory=DepthCheckConfig)
    telegram: TelegramDisplaySettings = Field(default_factory=TelegramDisplaySettings)
    config_source: str


class ScannerStatus(BaseModel):
    data_source: str
    data_source_mode: DataSourceMode
    mode: DataSourceMode
    scanner_health: Literal["ok", "degraded"]
    last_error: str | None
    last_updated: datetime | None
    snapshot_count: int = Field(ge=0)
    opportunity_count: int = Field(ge=0)
    total_opportunity_count: int = Field(ge=0)
    stored_opportunity_count: int = Field(ge=0)
    enabled_exchanges: tuple[str, ...]
    active_connectors: tuple[str, ...]
    symbol_selection_mode: SymbolSelectionMode
    selected_symbol_count: int = Field(ge=0)
    selected_symbols: tuple[str, ...] = ()
    symbol_selection_min_volume_24h_usd: float | None = None
    symbol_selection_max_volume_24h_usd: float | None = None
    symbols_on_2_exchanges: int = Field(default=0, ge=0)
    symbols_on_3_exchanges: int = Field(default=0, ge=0)
