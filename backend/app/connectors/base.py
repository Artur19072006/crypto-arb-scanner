from abc import ABC, abstractmethod

from app.domain.models import MarketSnapshot


class ExchangeConnector(ABC):
    name: str
    data_source: str

    @abstractmethod
    async def fetch_snapshots(self) -> list[MarketSnapshot]:
        """Return current bid/ask snapshots for USDT perpetual contracts."""

    # TODO: Add an async streaming interface for real exchange WebSocket feeds.
    # TODO: Add reconnect/backoff and per-exchange subscription management later.
