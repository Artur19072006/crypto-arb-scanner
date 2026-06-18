import asyncio
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from app.domain.models import (
    ArbitrageOpportunity,
    SpreadHistoryConfig,
    SpreadHistoryPoint,
)
from app.services.symbols import normalize_symbol


PROJECT_ROOT = Path(__file__).resolve().parents[3]


class SpreadHistoryStore:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._last_write_at_by_path: dict[Path, datetime] = {}
        self._last_pruned_at_by_path: dict[Path, datetime] = {}

    async def ensure_schema(self, sqlite_path: str | Path) -> None:
        path = _resolve_sqlite_path(sqlite_path)
        await asyncio.to_thread(_ensure_schema_sync, path)

    async def insert_opportunities(
        self,
        sqlite_path: str | Path,
        opportunities: list[ArbitrageOpportunity],
    ) -> int:
        if not opportunities:
            return 0

        path = _resolve_sqlite_path(sqlite_path)
        async with self._lock:
            return await asyncio.to_thread(_insert_opportunities_sync, path, opportunities)

    async def record_opportunities(
        self,
        config: SpreadHistoryConfig,
        opportunities: list[ArbitrageOpportunity],
        checked_at: datetime | None = None,
    ) -> int:
        if not config.enabled:
            return 0

        path = _resolve_sqlite_path(config.sqlite_path)
        now = checked_at or datetime.now(timezone.utc)
        async with self._lock:
            if not opportunities:
                await self._prune_old_rows_if_due(path, config, now)
                return 0

            last_write_at = self._last_write_at_by_path.get(path)
            if (
                last_write_at is not None
                and config.write_interval_seconds > 0
                and (now - last_write_at).total_seconds() < config.write_interval_seconds
            ):
                await self._prune_old_rows_if_due(path, config, now)
                return 0

            inserted = await asyncio.to_thread(
                _insert_opportunities_sync,
                path,
                opportunities,
            )
            self._last_write_at_by_path[path] = now
            await self._prune_old_rows_if_due(path, config, now)
            return inserted

    async def get_history(
        self,
        sqlite_path: str | Path,
        symbol: str,
        long_exchange: str,
        short_exchange: str,
        limit: int,
    ) -> list[SpreadHistoryPoint]:
        path = _resolve_sqlite_path(sqlite_path)
        return await asyncio.to_thread(
            _get_history_sync,
            path,
            normalize_symbol(symbol),
            long_exchange.lower().strip(),
            short_exchange.lower().strip(),
            limit,
        )

    async def _prune_old_rows_if_due(
        self,
        path: Path,
        config: SpreadHistoryConfig,
        now: datetime,
    ) -> int:
        last_pruned_at = self._last_pruned_at_by_path.get(path)
        if (
            last_pruned_at is not None
            and config.prune_interval_seconds > 0
            and (now - last_pruned_at).total_seconds()
            < config.prune_interval_seconds
        ):
            return 0

        cutoff = now - timedelta(hours=config.retention_hours)
        deleted = await asyncio.to_thread(_prune_old_rows_sync, path, cutoff)
        self._last_pruned_at_by_path[path] = now
        return deleted


def _resolve_sqlite_path(sqlite_path: str | Path) -> Path:
    path = Path(sqlite_path)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path


def _connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    return connection


def _ensure_schema_sync(path: Path) -> None:
    with closing(_connect(path)) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS spread_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                symbol TEXT NOT NULL,
                symbol_key TEXT NOT NULL,
                long_exchange TEXT NOT NULL,
                long_exchange_key TEXT NOT NULL,
                short_exchange TEXT NOT NULL,
                short_exchange_key TEXT NOT NULL,
                ask_price REAL NOT NULL,
                bid_price REAL NOT NULL,
                raw_spread_percent REAL NOT NULL,
                estimated_net_spread_percent REAL,
                depth_adjusted_net_spread_percent REAL,
                estimated_fee_percent REAL,
                volume_24h_usd REAL NOT NULL,
                long_funding_rate_percent REAL,
                short_funding_rate_percent REAL,
                funding_rate_difference_percent REAL,
                funding_impact TEXT,
                liquidity_status TEXT,
                depth_status TEXT
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_spread_history_pair_time
            ON spread_history (
                symbol_key,
                long_exchange_key,
                short_exchange_key,
                timestamp
            )
            """
        )
        connection.commit()


def _insert_opportunities_sync(
    path: Path,
    opportunities: list[ArbitrageOpportunity],
) -> int:
    _ensure_schema_sync(path)
    rows = [_opportunity_row(opportunity) for opportunity in opportunities]
    with closing(_connect(path)) as connection:
        connection.executemany(
            """
            INSERT INTO spread_history (
                timestamp,
                symbol,
                symbol_key,
                long_exchange,
                long_exchange_key,
                short_exchange,
                short_exchange_key,
                ask_price,
                bid_price,
                raw_spread_percent,
                estimated_net_spread_percent,
                depth_adjusted_net_spread_percent,
                estimated_fee_percent,
                volume_24h_usd,
                long_funding_rate_percent,
                short_funding_rate_percent,
                funding_rate_difference_percent,
                funding_impact,
                liquidity_status,
                depth_status
            ) VALUES (
                :timestamp,
                :symbol,
                :symbol_key,
                :long_exchange,
                :long_exchange_key,
                :short_exchange,
                :short_exchange_key,
                :ask_price,
                :bid_price,
                :raw_spread_percent,
                :estimated_net_spread_percent,
                :depth_adjusted_net_spread_percent,
                :estimated_fee_percent,
                :volume_24h_usd,
                :long_funding_rate_percent,
                :short_funding_rate_percent,
                :funding_rate_difference_percent,
                :funding_impact,
                :liquidity_status,
                :depth_status
            )
            """,
            rows,
        )
        connection.commit()
    return len(rows)


def _prune_old_rows_sync(path: Path, cutoff: datetime) -> int:
    if not path.exists():
        return 0

    _ensure_schema_sync(path)
    with closing(_connect(path)) as connection:
        cursor = connection.execute(
            """
            DELETE FROM spread_history
            WHERE timestamp < ?
            """,
            (cutoff.isoformat(),),
        )
        connection.commit()
        return cursor.rowcount


def _get_history_sync(
    path: Path,
    symbol_key: str,
    long_exchange_key: str,
    short_exchange_key: str,
    limit: int,
) -> list[SpreadHistoryPoint]:
    _ensure_schema_sync(path)
    with closing(_connect(path)) as connection:
        rows = connection.execute(
            """
            SELECT * FROM (
                SELECT *
                FROM spread_history
                WHERE symbol_key = ?
                  AND long_exchange_key = ?
                  AND short_exchange_key = ?
                ORDER BY timestamp DESC, id DESC
                LIMIT ?
            )
            ORDER BY timestamp ASC, id ASC
            """,
            (symbol_key, long_exchange_key, short_exchange_key, limit),
        ).fetchall()

    return [_history_point_from_row(row) for row in rows]


def _opportunity_row(opportunity: ArbitrageOpportunity) -> dict[str, Any]:
    depth = opportunity.depth_check
    return {
        "timestamp": opportunity.timestamp.isoformat(),
        "symbol": opportunity.symbol,
        "symbol_key": normalize_symbol(opportunity.symbol),
        "long_exchange": opportunity.long_exchange,
        "long_exchange_key": opportunity.long_exchange.lower().strip(),
        "short_exchange": opportunity.short_exchange,
        "short_exchange_key": opportunity.short_exchange.lower().strip(),
        "ask_price": opportunity.ask_price,
        "bid_price": opportunity.bid_price,
        "raw_spread_percent": opportunity.raw_spread_percent,
        "estimated_net_spread_percent": opportunity.estimated_net_spread_percent,
        "depth_adjusted_net_spread_percent": (
            depth.depth_adjusted_net_spread_percent if depth else None
        ),
        "estimated_fee_percent": opportunity.estimated_fee_percent,
        "volume_24h_usd": opportunity.volume_24h_usd,
        "long_funding_rate_percent": opportunity.long_funding_rate_percent,
        "short_funding_rate_percent": opportunity.short_funding_rate_percent,
        "funding_rate_difference_percent": opportunity.funding_rate_difference_percent,
        "funding_impact": opportunity.funding_impact,
        "liquidity_status": opportunity.liquidity_status,
        "depth_status": depth.depth_status if depth else None,
    }


def _history_point_from_row(row: sqlite3.Row) -> SpreadHistoryPoint:
    selected_spread_percent = _selected_spread_percent(row)
    return SpreadHistoryPoint(
        timestamp=datetime.fromisoformat(row["timestamp"]),
        symbol=row["symbol"],
        long_exchange=row["long_exchange"],
        short_exchange=row["short_exchange"],
        ask_price=row["ask_price"],
        bid_price=row["bid_price"],
        raw_spread_percent=row["raw_spread_percent"],
        estimated_net_spread_percent=row["estimated_net_spread_percent"],
        depth_adjusted_net_spread_percent=row["depth_adjusted_net_spread_percent"],
        estimated_fee_percent=row["estimated_fee_percent"],
        volume_24h_usd=row["volume_24h_usd"],
        long_funding_rate_percent=row["long_funding_rate_percent"],
        short_funding_rate_percent=row["short_funding_rate_percent"],
        funding_rate_difference_percent=row["funding_rate_difference_percent"],
        funding_impact=row["funding_impact"],
        liquidity_status=row["liquidity_status"],
        depth_status=row["depth_status"],
        selected_spread_percent=selected_spread_percent,
        lower_line_percent=-(selected_spread_percent / 2),
        upper_line_percent=selected_spread_percent / 2,
    )


def _selected_spread_percent(row: sqlite3.Row) -> float:
    for field in (
        "depth_adjusted_net_spread_percent",
        "estimated_net_spread_percent",
        "raw_spread_percent",
    ):
        value = row[field]
        if value is not None:
            return float(value)
    return 0.0
