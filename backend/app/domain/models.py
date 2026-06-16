from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


LiquidityStatus = Literal["OK", "Thin", "Holey"]
FundingImpact = Literal["Good", "Neutral", "Bad"]


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
