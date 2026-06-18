import sqlite3
import unittest
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from app.api.routes import get_spread_history
from app.connectors.base import ExchangeConnector
from app.connectors.registry import ConnectorRegistry
from app.core.config import load_app_config
from app.db.spread_history import SpreadHistoryStore
from app.domain.models import (
    ArbitrageOpportunity,
    DepthCheckResult,
    MarketSnapshot,
    SpreadHistoryConfig,
)
from app.services.live_scanner import refresh_mock_scanner_once
from app.services.market_data_cache import MarketDataCache
from app.services.opportunity_store import OpportunityStore


class SpreadHistoryStoreTests(unittest.IsolatedAsyncioTestCase):
    async def test_ensure_schema_creates_spread_history_table(self) -> None:
        with TemporaryDirectory() as temp_dir:
            sqlite_path = Path(temp_dir) / "spread_history.sqlite"
            store = SpreadHistoryStore()

            await store.ensure_schema(sqlite_path)

            with closing(sqlite3.connect(sqlite_path)) as connection:
                table_names = {
                    row[0]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    ).fetchall()
                }

        self.assertIn("spread_history", table_names)

    async def test_insert_spread_history_row_with_chart_values(self) -> None:
        with TemporaryDirectory() as temp_dir:
            sqlite_path = Path(temp_dir) / "spread_history.sqlite"
            store = SpreadHistoryStore()

            inserted = await store.insert_opportunities(
                sqlite_path,
                [_opportunity(depth_adjusted_net_spread_percent=0.42)],
            )
            rows = await store.get_history(
                sqlite_path,
                symbol="btcusdt",
                long_exchange="binance",
                short_exchange="bybit",
                limit=500,
            )

        self.assertEqual(inserted, 1)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row.symbol, "BTCUSDT")
        self.assertEqual(row.long_exchange, "Binance")
        self.assertEqual(row.short_exchange, "Bybit")
        self.assertEqual(row.ask_price, 100.0)
        self.assertEqual(row.bid_price, 101.0)
        self.assertEqual(row.depth_adjusted_net_spread_percent, 0.42)
        self.assertEqual(row.selected_spread_percent, 0.42)
        self.assertEqual(row.lower_line_percent, -0.21)
        self.assertEqual(row.upper_line_percent, 0.21)
        self.assertEqual(row.depth_status, "OK")

    async def test_disabled_history_does_not_write(self) -> None:
        with TemporaryDirectory() as temp_dir:
            sqlite_path = Path(temp_dir) / "spread_history.sqlite"
            store = SpreadHistoryStore()
            config = SpreadHistoryConfig(
                enabled=False,
                sqlite_path=str(sqlite_path),
            )

            inserted = await store.record_opportunities(config, [_opportunity()])

            self.assertEqual(inserted, 0)
            self.assertFalse(sqlite_path.exists())

    async def test_disabled_history_does_not_prune_existing_rows(self) -> None:
        checked_at = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
        old_timestamp = checked_at - timedelta(hours=169)
        with TemporaryDirectory() as temp_dir:
            sqlite_path = Path(temp_dir) / "spread_history.sqlite"
            store = SpreadHistoryStore()
            await store.insert_opportunities(
                sqlite_path,
                [_opportunity(timestamp=old_timestamp)],
            )
            config = SpreadHistoryConfig(
                enabled=False,
                sqlite_path=str(sqlite_path),
                retention_hours=168,
                prune_interval_seconds=0,
            )

            inserted = await store.record_opportunities(
                config,
                [_opportunity(symbol="ETHUSDT", timestamp=checked_at)],
                checked_at=checked_at,
            )
            rows = await store.get_history(
                sqlite_path,
                symbol="BTCUSDT",
                long_exchange="Binance",
                short_exchange="Bybit",
                limit=500,
            )

        self.assertEqual(inserted, 0)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].timestamp, old_timestamp)

    async def test_record_opportunities_prunes_old_rows_and_keeps_recent_rows(self) -> None:
        checked_at = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
        old_timestamp = checked_at - timedelta(hours=169)
        recent_timestamp = checked_at - timedelta(hours=1)
        with TemporaryDirectory() as temp_dir:
            sqlite_path = Path(temp_dir) / "spread_history.sqlite"
            store = SpreadHistoryStore()
            await store.insert_opportunities(
                sqlite_path,
                [
                    _opportunity(timestamp=old_timestamp),
                    _opportunity(timestamp=recent_timestamp),
                ],
            )
            config = SpreadHistoryConfig(
                enabled=True,
                sqlite_path=str(sqlite_path),
                write_interval_seconds=0,
                retention_hours=168,
                prune_interval_seconds=3600,
            )

            await store.record_opportunities(
                config,
                [_opportunity(symbol="ETHUSDT", timestamp=checked_at)],
                checked_at=checked_at,
            )
            rows = await store.get_history(
                sqlite_path,
                symbol="BTCUSDT",
                long_exchange="Binance",
                short_exchange="Bybit",
                limit=500,
            )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].timestamp, recent_timestamp)

    async def test_pruning_respects_prune_interval_seconds(self) -> None:
        checked_at = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
        with TemporaryDirectory() as temp_dir:
            sqlite_path = Path(temp_dir) / "spread_history.sqlite"
            store = SpreadHistoryStore()
            config = SpreadHistoryConfig(
                enabled=True,
                sqlite_path=str(sqlite_path),
                write_interval_seconds=0,
                retention_hours=168,
                prune_interval_seconds=3600,
            )

            await store.insert_opportunities(
                sqlite_path,
                [_opportunity(timestamp=checked_at - timedelta(hours=169))],
            )
            await store.record_opportunities(
                config,
                [_opportunity(symbol="ETHUSDT", timestamp=checked_at)],
                checked_at=checked_at,
            )
            await store.insert_opportunities(
                sqlite_path,
                [
                    _opportunity(
                        symbol="SOLUSDT",
                        timestamp=checked_at - timedelta(hours=170),
                    )
                ],
            )

            await store.record_opportunities(
                config,
                [
                    _opportunity(
                        symbol="ETHUSDT",
                        timestamp=checked_at + timedelta(seconds=3599),
                    )
                ],
                checked_at=checked_at + timedelta(seconds=3599),
            )
            rows_before_interval = await store.get_history(
                sqlite_path,
                symbol="SOLUSDT",
                long_exchange="Binance",
                short_exchange="Bybit",
                limit=500,
            )

            await store.record_opportunities(
                config,
                [
                    _opportunity(
                        symbol="ETHUSDT",
                        timestamp=checked_at + timedelta(seconds=3600),
                    )
                ],
                checked_at=checked_at + timedelta(seconds=3600),
            )
            rows_after_interval = await store.get_history(
                sqlite_path,
                symbol="SOLUSDT",
                long_exchange="Binance",
                short_exchange="Bybit",
                limit=500,
            )

        self.assertEqual(len(rows_before_interval), 1)
        self.assertEqual(rows_after_interval, [])

    async def test_spread_history_api_filters_pair_and_returns_chart_values(self) -> None:
        with TemporaryDirectory() as temp_dir:
            sqlite_path = Path(temp_dir) / "spread_history.sqlite"
            store = SpreadHistoryStore()
            await store.insert_opportunities(
                sqlite_path,
                [
                    _opportunity("BTCUSDT", "Binance", "Bybit", net_spread=0.30),
                    _opportunity("BTCUSDT", "Bybit", "Binance", net_spread=0.50),
                    _opportunity("ETHUSDT", "Binance", "Bybit", net_spread=0.70),
                ],
            )
            config = _config_with_history(sqlite_path)

            with (
                patch("app.api.routes.get_app_config", return_value=config),
                patch("app.api.routes.spread_history_store", store),
            ):
                response = await get_spread_history(
                    symbol="btcusdt",
                    long_exchange="binance",
                    short_exchange="bybit",
                    limit="500",
                )

        self.assertEqual(response.symbol, "BTCUSDT")
        self.assertEqual(response.long_exchange, "Binance")
        self.assertEqual(response.short_exchange, "Bybit")
        self.assertEqual(response.returned_count, 1)
        self.assertEqual(response.rows[0].selected_spread_percent, 0.30)
        self.assertEqual(response.rows[0].lower_line_percent, -0.15)
        self.assertEqual(response.rows[0].upper_line_percent, 0.15)

    async def test_scanner_writes_history_when_enabled(self) -> None:
        with TemporaryDirectory() as temp_dir:
            sqlite_path = Path(temp_dir) / "spread_history.sqlite"
            config = _live_config_with_history(sqlite_path)
            store = OpportunityStore()
            history_store = SpreadHistoryStore()
            registry = ConnectorRegistry()
            registry.register(
                StaticSnapshotConnector(
                    "binance",
                    _snapshot("Binance", bid=99.0, ask=100.0),
                )
            )
            registry.register(
                StaticSnapshotConnector(
                    "bybit",
                    _snapshot("Bybit", bid=101.0, ask=102.0),
                )
            )

            await refresh_mock_scanner_once(
                cache=MarketDataCache(),
                store=store,
                registry=registry,
                websocket_manager=NoopWebSocketManager(),
                history_store=history_store,
                config=config,
            )
            rows = await history_store.get_history(
                sqlite_path,
                "BTCUSDT",
                "Binance",
                "Bybit",
                500,
            )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].selected_spread_percent, rows[0].estimated_net_spread_percent)


class StaticSnapshotConnector(ExchangeConnector):
    data_source = "test_rest"

    def __init__(self, name: str, snapshot: MarketSnapshot) -> None:
        self.name = name
        self.snapshot = snapshot

    async def fetch_snapshots(
        self,
        symbols: tuple[str, ...] | None = None,
    ) -> list[MarketSnapshot]:
        if symbols and self.snapshot.symbol not in symbols:
            return []
        return [self.snapshot]


class NoopWebSocketManager:
    async def ensure_started(self, config, symbols_by_connector) -> None:
        return None

    async def stop(self) -> None:
        return None


def _config_with_history(sqlite_path: Path):
    return _load_config(
        f"""
history:
  enabled: true
  sqlite_path: "{sqlite_path.as_posix()}"
  write_interval_seconds: 0
"""
    )


def _live_config_with_history(sqlite_path: Path):
    return _load_config(
        f"""
data_source_mode: live
enabled_connectors:
  - binance
  - bybit
max_symbols: 1
symbol_allowlist:
  - BTCUSDT
symbol_selection:
  mode: manual
filters:
  min_raw_spread: 0
  min_net_spread: -10
  min_volume_24h_usd: 0
  enabled_exchanges:
    - Binance
    - Bybit
history:
  enabled: true
  sqlite_path: "{sqlite_path.as_posix()}"
  write_interval_seconds: 0
"""
    )


def _load_config(contents: str):
    with TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        config_path = root / "config.yaml"
        config_path.write_text(contents, encoding="utf-8")
        return load_app_config(
            config_path=config_path,
            example_path=root / "config.example.yaml",
        )


def _snapshot(exchange: str, bid: float, ask: float) -> MarketSnapshot:
    return MarketSnapshot(
        exchange=exchange,
        symbol="BTCUSDT",
        best_bid=bid,
        best_bid_size=10.0,
        best_ask=ask,
        best_ask_size=10.0,
        volume_24h_usd=1_000_000,
        funding_rate_percent=0.01,
        next_funding_time=None,
        timestamp=datetime.now(timezone.utc),
    )


def _opportunity(
    symbol: str = "BTCUSDT",
    long_exchange: str = "Binance",
    short_exchange: str = "Bybit",
    raw_spread: float = 0.50,
    net_spread: float = 0.30,
    depth_adjusted_net_spread_percent: float | None = None,
    timestamp: datetime | None = None,
) -> ArbitrageOpportunity:
    depth_check = None
    if depth_adjusted_net_spread_percent is not None:
        depth_check = DepthCheckResult(
            target_notional_usd=500,
            can_fill_long=True,
            can_fill_short=True,
            long_effective_price=100.0,
            short_effective_price=101.0,
            long_slippage_percent=0.01,
            short_slippage_percent=0.02,
            depth_adjusted_raw_spread_percent=0.62,
            depth_adjusted_net_spread_percent=depth_adjusted_net_spread_percent,
            depth_status="OK",
        )

    return ArbitrageOpportunity(
        symbol=symbol,
        long_exchange=long_exchange,
        short_exchange=short_exchange,
        ask_price=100.0,
        bid_price=101.0,
        raw_spread_percent=raw_spread,
        estimated_net_spread_percent=net_spread,
        estimated_fee_percent=max(raw_spread - net_spread, 0),
        volume_24h_usd=1_000_000,
        best_ask_size=10.0,
        best_bid_size=10.0,
        long_funding_rate_percent=0.01,
        short_funding_rate_percent=0.02,
        funding_rate_difference_percent=0.01,
        next_funding_time=None,
        funding_impact="Good",
        liquidity_status="OK",
        depth_check=depth_check,
        timestamp=timestamp or datetime.now(timezone.utc),
    )


if __name__ == "__main__":
    unittest.main()
