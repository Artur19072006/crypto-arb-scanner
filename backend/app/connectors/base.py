from abc import ABC, abstractmethod

from app.domain.models import MarketSnapshot


class ExchangeConnector(ABC):
    name: str

    @abstractmethod
    async def get_snapshots(self) -> list[MarketSnapshot]:
        """Return current bid/ask snapshots for USDT perpetual contracts."""
