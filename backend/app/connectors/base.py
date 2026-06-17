from abc import ABC, abstractmethod

from app.domain.models import MarketSnapshot, MarketSymbol, OrderBookSnapshot


class ExchangeConnector(ABC):
    name: str
    data_source: str

    @abstractmethod
    async def fetch_snapshots(
        self,
        symbols: tuple[str, ...] | None = None,
    ) -> list[MarketSnapshot]:
        """Return current bid/ask snapshots for USDT perpetual contracts."""

    async def fetch_symbol_markets(self) -> list[MarketSymbol]:
        """Return public symbol metadata for universe selection when available."""
        return []

    async def fetch_order_book(
        self,
        symbol: str,
        limit: int = 50,
    ) -> OrderBookSnapshot:
        """Return a public REST order book snapshot when the connector supports it."""
        raise NotImplementedError(f"{self.name} does not support public order books")

    # TODO: Add an async streaming interface for real exchange WebSocket feeds.
    # TODO: Add reconnect/backoff and per-exchange subscription management later.
