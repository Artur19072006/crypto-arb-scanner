import asyncio

from app.domain.models import MarketSnapshot


class MarketDataCache:
    def __init__(self) -> None:
        self._snapshots: dict[tuple[str, str], MarketSnapshot] = {}
        self._lock = asyncio.Lock()

    async def update_snapshots(self, snapshots: list[MarketSnapshot]) -> None:
        async with self._lock:
            for snapshot in snapshots:
                self._snapshots[(snapshot.symbol, snapshot.exchange)] = snapshot

    async def get_all_snapshots(self) -> list[MarketSnapshot]:
        async with self._lock:
            return [
                self._snapshots[key]
                for key in sorted(self._snapshots)
            ]

    async def snapshot_count(self) -> int:
        async with self._lock:
            return len(self._snapshots)
