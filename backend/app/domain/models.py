from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


LiquidityStatus = Literal["OK", "Thin", "Holey"]
DepthStatus = Literal["OK", "Thin", "Insufficient", "Unknown"]
FundingImpact = Literal["Good", "Neutral", "Bad"]
DataSourceMode = Literal["mock", "live"]
MarketDataMode = Literal["rest", "websocket"]
SymbolSelectionMode = Literal["manual", "auto"]
AlertSeverity = Literal["Info", "Watch", "Strong"]
TelegramParseMode = Literal["HTML", "Markdown", "MarkdownV2"]
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
    source: str = "rest"


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


class AlertCandidate(BaseModel):
    id: str
    alert_key: str
    symbol: str
    long_exchange: str
    short_exchange: str
    ask_price: float | None = Field(default=None, gt=0)
    bid_price: float | None = Field(default=None, gt=0)
    raw_spread_percent: float
    estimated_net_spread_percent: float
    estimated_fee_percent: float | None = Field(default=None, ge=0)
    depth_adjusted_net_spread_percent: float | None = None
    depth_status: DepthStatus | None = None
    target_notional_usd: float | None = None
    long_slippage_percent: float | None = None
    short_slippage_percent: float | None = None
    long_funding_rate_percent: float | None = None
    short_funding_rate_percent: float | None = None
    funding_rate_difference_percent: float | None = None
    next_funding_time: datetime | None = None
    volume_24h_usd: float | None = Field(default=None, ge=0)
    funding_impact: FundingImpact
    liquidity_status: LiquidityStatus
    alert_score: float
    severity: AlertSeverity
    reasons: list[str] = Field(default_factory=list)
    created_at: datetime
    suppressed: bool = False
    suppression_reason: str | None = None


class AlertEvent(AlertCandidate):
    pass


class AlertsResponse(BaseModel):
    alerts: list[AlertCandidate]
    active_alert_count: int = Field(ge=0)


class AlertHistoryResponse(BaseModel):
    alerts: list[AlertEvent]
    returned_count: int = Field(ge=0)


class AlertStatusResponse(BaseModel):
    enabled: bool
    cooldown_seconds: int = Field(ge=0)
    active_alert_count: int = Field(ge=0)
    suppressed_count: int = Field(ge=0)
    last_evaluated_at: datetime | None


class TelegramStatusResponse(BaseModel):
    enabled: bool
    configured: bool
    last_sent_at: datetime | None
    sent_count: int = Field(ge=0)
    last_error: str | None
    tracked_alert_keys_count: int = Field(default=0, ge=0)


class TelegramDisplaySettings(BaseModel):
    enabled: bool = False
    bot_token_env: str = "TELEGRAM_BOT_TOKEN"
    chat_id_env: str = "TELEGRAM_CHAT_ID"
    parse_mode: TelegramParseMode = "HTML"
    timeout_seconds: int = Field(default=10, ge=1)


class WebSocketMarketDataConfig(BaseModel):
    enabled: bool = False
    exchanges: tuple[str, ...] = ("binance", "bybit", "okx", "bitget", "gate")
    reconnect_seconds: int = Field(default=5, ge=1)
    stale_after_seconds: int = Field(default=20, ge=1)
    max_symbols_per_connection: int = Field(default=50, ge=1)
    connection_start_delay_seconds: float = Field(default=0.25, ge=0)
    max_reconnect_attempts: int = Field(default=0, ge=0)


class MarketDataConfig(BaseModel):
    mode: MarketDataMode = "rest"
    websocket: WebSocketMarketDataConfig = Field(
        default_factory=WebSocketMarketDataConfig
    )


class SpreadHistoryConfig(BaseModel):
    enabled: bool = False
    sqlite_path: str = "data/spread_history.sqlite"
    write_interval_seconds: int = Field(default=10, ge=0)
    retention_hours: int = Field(default=168, ge=1)
    prune_interval_seconds: int = Field(default=3600, ge=0)


class SpreadHistoryPoint(BaseModel):
    timestamp: datetime
    symbol: str
    long_exchange: str
    short_exchange: str
    ask_price: float = Field(gt=0)
    bid_price: float = Field(gt=0)
    raw_spread_percent: float
    estimated_net_spread_percent: float | None = None
    depth_adjusted_net_spread_percent: float | None = None
    estimated_fee_percent: float | None = Field(default=None, ge=0)
    volume_24h_usd: float = Field(ge=0)
    long_funding_rate_percent: float | None = None
    short_funding_rate_percent: float | None = None
    funding_rate_difference_percent: float | None = None
    funding_impact: FundingImpact | None = None
    liquidity_status: LiquidityStatus | None = None
    depth_status: DepthStatus | None = None
    selected_spread_percent: float
    lower_line_percent: float
    upper_line_percent: float


class SpreadHistoryResponse(BaseModel):
    symbol: str
    long_exchange: str
    short_exchange: str
    limit: int = Field(ge=1)
    returned_count: int = Field(ge=0)
    rows: list[SpreadHistoryPoint]


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


class AlertConfig(BaseModel):
    enabled: bool = False
    min_net_spread_percent: float = 0.15
    min_depth_adjusted_net_spread_percent: float = 0.05
    require_depth_status: tuple[DepthStatus, ...] = ("OK", "Thin")
    max_allowed_slippage_percent: float = Field(default=0.3, ge=0)
    min_volume_24h_usd: float = Field(default=400_000, ge=0)
    cooldown_seconds: int = Field(default=300, ge=0)
    max_alerts_per_scan: int = Field(default=5, ge=1)


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
    alerts: AlertConfig = Field(default_factory=AlertConfig)
    telegram: TelegramDisplaySettings = Field(default_factory=TelegramDisplaySettings)
    market_data: MarketDataConfig = Field(default_factory=MarketDataConfig)
    history: SpreadHistoryConfig = Field(default_factory=SpreadHistoryConfig)
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
    market_data_mode: MarketDataMode = "rest"
    websocket_enabled: bool = False
    websocket_active_exchanges: tuple[str, ...] = ()
    websocket_connected: dict[str, bool] = Field(default_factory=dict)
    websocket_connection_count: dict[str, int] = Field(default_factory=dict)
    websocket_chunk_count: dict[str, int] = Field(default_factory=dict)
    websocket_symbol_count: dict[str, int] = Field(default_factory=dict)
    websocket_last_message_at: dict[str, datetime | None] = Field(default_factory=dict)
    websocket_last_error: dict[str, str | None] = Field(default_factory=dict)
    websocket_reconnect_count: dict[str, int] = Field(default_factory=dict)
    stale_snapshot_count: int = Field(default=0, ge=0)
    last_websocket_update_at: datetime | None = None
    symbol_selection_mode: SymbolSelectionMode
    selected_symbol_count: int = Field(ge=0)
    selected_symbols: tuple[str, ...] = ()
    symbol_selection_min_volume_24h_usd: float | None = None
    symbol_selection_max_volume_24h_usd: float | None = None
    symbols_on_2_exchanges: int = Field(default=0, ge=0)
    symbols_on_3_exchanges: int = Field(default=0, ge=0)
