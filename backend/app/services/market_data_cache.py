import asyncio
from collections.abc import Iterable
from datetime import datetime, timezone

from app.domain.models import MarketSnapshot


class MarketDataCache:
    def __init__(self) -> None:
        self._snapshots: dict[tuple[str, str, str], MarketSnapshot] = {}
        self._lock = asyncio.Lock()

    async def update_snapshots(
        self,
        snapshots: list[MarketSnapshot],
        source: str | None = None,
    ) -> None:
        async with self._lock:
            for snapshot in snapshots:
                active_source = source or snapshot.source
                stored_snapshot = (
                    snapshot
                    if snapshot.source == active_source
                    else snapshot.model_copy(update={"source": active_source})
                )
                self._snapshots[
                    (
                        stored_snapshot.symbol,
                        stored_snapshot.exchange,
                        active_source,
                    )
                ] = stored_snapshot

    async def get_all_snapshots(self) -> list[MarketSnapshot]:
        async with self._lock:
            return _preferred_latest_snapshots(
                list(self._snapshots.values()),
                preferred_source=None,
                stale_after_seconds=None,
            )

    async def get_preferred_snapshots(
        self,
        preferred_source: str,
        stale_after_seconds: int,
        checked_at: datetime | None = None,
    ) -> list[MarketSnapshot]:
        async with self._lock:
            return _preferred_latest_snapshots(
                list(self._snapshots.values()),
                preferred_source=preferred_source,
                stale_after_seconds=stale_after_seconds,
                checked_at=checked_at,
            )

    async def stale_snapshot_count(
        self,
        source: str,
        stale_after_seconds: int,
        checked_at: datetime | None = None,
    ) -> int:
        now = checked_at or datetime.now(timezone.utc)
        async with self._lock:
            return sum(
                1
                for snapshot in self._snapshots.values()
                if snapshot.source == source
                and _is_stale(snapshot, stale_after_seconds, now)
            )

    async def last_update_at(self, source: str | None = None) -> datetime | None:
        async with self._lock:
            timestamps = [
                snapshot.timestamp
                for snapshot in self._snapshots.values()
                if source is None or snapshot.source == source
            ]
        if not timestamps:
            return None

        return max(timestamps)

    async def snapshot_count(self) -> int:
        async with self._lock:
            return len({
                (snapshot.symbol, snapshot.exchange)
                for snapshot in self._snapshots.values()
            })


def _preferred_latest_snapshots(
    snapshots: list[MarketSnapshot],
    preferred_source: str | None,
    stale_after_seconds: int | None,
    checked_at: datetime | None = None,
) -> list[MarketSnapshot]:
    by_pair: dict[tuple[str, str], list[MarketSnapshot]] = {}
    for snapshot in snapshots:
        by_pair.setdefault((snapshot.symbol, snapshot.exchange), []).append(snapshot)

    now = checked_at or datetime.now(timezone.utc)
    preferred: list[MarketSnapshot] = []
    for key in sorted(by_pair):
        pair_snapshots = by_pair[key]
        rest_snapshot = _latest_snapshot(
            snapshot for snapshot in pair_snapshots if snapshot.source == "rest"
        )
        preferred_snapshot = (
            _latest_snapshot(
                snapshot
                for snapshot in pair_snapshots
                if snapshot.source == preferred_source
                and not _is_stale(snapshot, stale_after_seconds, now)
            )
            if preferred_source and stale_after_seconds is not None
            else None
        )

        if preferred_snapshot is not None and rest_snapshot is not None:
            preferred.append(_merge_top_of_book(preferred_snapshot, rest_snapshot))
        elif preferred_snapshot is not None:
            preferred.append(preferred_snapshot)
        elif rest_snapshot is not None:
            preferred.append(rest_snapshot)
        else:
            latest = _latest_snapshot(pair_snapshots)
            if latest is not None:
                preferred.append(latest)

    return preferred


def _latest_snapshot(snapshots: Iterable[MarketSnapshot]) -> MarketSnapshot | None:
    snapshot_list = list(snapshots)
    if not snapshot_list:
        return None

    return max(snapshot_list, key=lambda snapshot: snapshot.timestamp)


def _merge_top_of_book(
    top_of_book: MarketSnapshot,
    context: MarketSnapshot,
) -> MarketSnapshot:
    return context.model_copy(
        update={
            "best_bid": top_of_book.best_bid,
            "best_bid_size": top_of_book.best_bid_size,
            "best_ask": top_of_book.best_ask,
            "best_ask_size": top_of_book.best_ask_size,
            "timestamp": top_of_book.timestamp,
            "source": top_of_book.source,
        }
    )


def _is_stale(
    snapshot: MarketSnapshot,
    stale_after_seconds: int | None,
    checked_at: datetime,
) -> bool:
    if stale_after_seconds is None:
        return False

    return (checked_at - snapshot.timestamp).total_seconds() > stale_after_seconds
