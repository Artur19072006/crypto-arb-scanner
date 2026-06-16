import asyncio
from datetime import datetime, timezone

from app.domain.models import ArbitrageOpportunity


class OpportunityStore:
    def __init__(self) -> None:
        self._opportunities: list[ArbitrageOpportunity] = []
        self._last_updated: datetime | None = None
        self._lock = asyncio.Lock()

    async def update_opportunities(
        self,
        opportunities: list[ArbitrageOpportunity],
        updated_at: datetime | None = None,
    ) -> None:
        async with self._lock:
            self._opportunities = list(opportunities)
            self._last_updated = updated_at or datetime.now(timezone.utc)

    async def get_all_opportunities(self) -> list[ArbitrageOpportunity]:
        async with self._lock:
            return list(self._opportunities)

    async def get_last_updated(self) -> datetime | None:
        async with self._lock:
            return self._last_updated

    async def opportunity_count(self) -> int:
        async with self._lock:
            return len(self._opportunities)
