from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


LiquidityStatus = Literal["OK", "Thin", "Holey"]
FundingImpact = Literal["Good", "Neutral", "Bad"]
DataSourceMode = Literal["mock", "live"]


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
    volume_24h_usd: float = Field(ge=0)
    best_ask_size: float = Field(ge=0)
    best_bid_size: float = Field(ge=0)
    long_funding_rate_percent: float
    short_funding_rate_percent: float
    funding_rate_difference_percent: float
    next_funding_time: datetime | None
    funding_impact: FundingImpact
    liquidity_status: LiquidityStatus
    timestamp: datetime


class ScannerFilters(BaseModel):
    min_raw_spread: float | None = Field(default=None, ge=0)
    min_net_spread: float | None = None
    min_volume_24h_usd: float | None = Field(default=None, ge=0)
    exchanges: tuple[str, ...] = ()


class TelegramDisplaySettings(BaseModel):
    enabled: bool = False
    alert_cooldown_seconds: int = Field(default=300, ge=0)


class AppConfig(BaseModel):
    data_source_mode: DataSourceMode = "mock"
    enabled_connectors: tuple[str, ...] = ("fake",)
    max_symbols: int = Field(default=10, ge=1)
    symbol_allowlist: tuple[str, ...] = ()
    fees: dict[str, ExchangeFees]
    default_filters: ScannerFilters
    supported_exchanges: tuple[str, ...]
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
