from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class MarketSnapshot:
    exchange: str
    symbol: str
    best_bid: float
    best_bid_size: float
    best_ask: float
    best_ask_size: float
    volume_24h_usd: float
    funding_rate_percent: float
    next_funding_time: datetime | None
    timestamp: datetime


class ExchangeConnector(ABC):
    name: str

    @abstractmethod
    async def get_snapshots(self) -> list[MarketSnapshot]:
        """Return current bid/ask snapshots for USDT perpetual contracts."""
