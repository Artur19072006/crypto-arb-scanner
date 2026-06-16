from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


LiquidityStatus = Literal["OK", "Thin", "Holey"]
FundingImpact = Literal["Good", "Neutral", "Bad"]


class Opportunity(BaseModel):
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
