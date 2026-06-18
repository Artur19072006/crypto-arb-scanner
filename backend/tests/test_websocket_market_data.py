import asyncio
import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from app.connectors.websocket import PublicWebSocketConnector
from app.core.config import load_app_config
from app.domain.models import MarketSnapshot
from app.services.market_data_cache import MarketDataCache
from app.services.websocket_market_data import WebSocketMarketDataManager, _chunk_symbols


class WebSocketSymbolChunkingTests(unittest.TestCase):
    def test_chunk_symbols_preserves_small_symbol_lists_as_one_chunk(self) -> None:
        chunks = _chunk_symbols(("BTCUSDT", "ETHUSDT"), 50)

        self.assertEqual(chunks, (("BTCUSDT", "ETHUSDT"),))

    def test_chunk_symbols_splits_large_symbol_lists(self) -> None:
        chunks = _chunk_symbols(
            ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT"),
            2,
        )

        self.assertEqual(
            chunks,
            (
                ("BTCUSDT", "ETHUSDT"),
                ("SOLUSDT", "XRPUSDT"),
                ("ADAUSDT",),
            ),
        )


class WebSocketMarketDataManagerTests(unittest.IsolatedAsyncioTestCase):
    async def test_websocket_snapshots_update_cache_and_status(self) -> None:
        cache = MarketDataCache()
        manager = WebSocketMarketDataManager(
            cache,
            connector_factory=lambda exchanges, reconnect_seconds, max_reconnect_attempts: [
                OneShotWebSocketConnector("binance", "Binance")
            ],
        )

        await manager.ensure_started(
            _live_websocket_config(),
            {"binance": ("BTCUSDT",)},
        )
        await _wait_for_snapshot(cache)
        status = await manager.status()

        snapshots = await cache.get_all_snapshots()

        self.assertEqual(len(snapshots), 1)
        self.assertEqual(snapshots[0].exchange, "Binance")
        self.assertEqual(snapshots[0].symbol, "BTCUSDT")
        self.assertEqual(snapshots[0].source, "websocket")
        self.assertEqual(status.active_exchanges, ("binance",))
        self.assertTrue(status.connected["binance"])
        self.assertEqual(status.connection_count["binance"], 1)
        self.assertEqual(status.chunk_count["binance"], 1)
        self.assertEqual(status.symbol_count["binance"], 1)
        self.assertIsNotNone(status.last_message_at["binance"])
        self.assertIsNotNone(status.last_update_at)

        await manager.stop()
        stopped_status = await manager.status()
        self.assertEqual(stopped_status.active_exchanges, ())
        self.assertEqual(stopped_status.connected, {})

    async def test_okx_websocket_snapshot_updates_cache_and_status(self) -> None:
        cache = MarketDataCache()
        manager = WebSocketMarketDataManager(
            cache,
            connector_factory=lambda exchanges, reconnect_seconds, max_reconnect_attempts: [
                OneShotWebSocketConnector("okx", "OKX")
            ],
        )

        await manager.ensure_started(
            _live_websocket_config(
                enabled_connectors=("okx",),
                websocket_exchanges=("okx",),
            ),
            {"okx": ("BTCUSDT",)},
        )
        await _wait_for_snapshot(cache)
        status = await manager.status()

        snapshots = await cache.get_all_snapshots()

        self.assertEqual(len(snapshots), 1)
        self.assertEqual(snapshots[0].exchange, "OKX")
        self.assertEqual(snapshots[0].symbol, "BTCUSDT")
        self.assertEqual(status.active_exchanges, ("okx",))
        self.assertTrue(status.connected["okx"])

        await manager.stop()

    async def test_bitget_websocket_snapshot_updates_cache_and_status(self) -> None:
        cache = MarketDataCache()
        manager = WebSocketMarketDataManager(
            cache,
            connector_factory=lambda exchanges, reconnect_seconds, max_reconnect_attempts: [
                OneShotWebSocketConnector("bitget", "Bitget")
            ],
        )

        await manager.ensure_started(
            _live_websocket_config(
                enabled_connectors=("bitget",),
                websocket_exchanges=("bitget",),
            ),
            {"bitget": ("BTCUSDT",)},
        )
        await _wait_for_snapshot(cache)
        status = await manager.status()

        snapshots = await cache.get_all_snapshots()

        self.assertEqual(len(snapshots), 1)
        self.assertEqual(snapshots[0].exchange, "Bitget")
        self.assertEqual(snapshots[0].symbol, "BTCUSDT")
        self.assertEqual(status.active_exchanges, ("bitget",))
        self.assertTrue(status.connected["bitget"])
        self.assertEqual(status.connection_count["bitget"], 1)
        self.assertEqual(status.chunk_count["bitget"], 1)
        self.assertEqual(status.symbol_count["bitget"], 1)
        self.assertIsNotNone(status.last_message_at["bitget"])

        await manager.stop()

    async def test_gate_websocket_snapshot_updates_cache_and_status(self) -> None:
        cache = MarketDataCache()
        manager = WebSocketMarketDataManager(
            cache,
            connector_factory=lambda exchanges, reconnect_seconds, max_reconnect_attempts: [
                OneShotWebSocketConnector("gate", "Gate")
            ],
        )

        await manager.ensure_started(
            _live_websocket_config(
                enabled_connectors=("gate",),
                websocket_exchanges=("gate",),
            ),
            {"gate": ("BTCUSDT",)},
        )
        await _wait_for_snapshot(cache)
        status = await manager.status()

        snapshots = await cache.get_all_snapshots()

        self.assertEqual(len(snapshots), 1)
        self.assertEqual(snapshots[0].exchange, "Gate")
        self.assertEqual(snapshots[0].symbol, "BTCUSDT")
        self.assertEqual(status.active_exchanges, ("gate",))
        self.assertTrue(status.connected["gate"])
        self.assertEqual(status.connection_count["gate"], 1)
        self.assertEqual(status.chunk_count["gate"], 1)
        self.assertEqual(status.symbol_count["gate"], 1)
        self.assertIsNotNone(status.last_message_at["gate"])

        await manager.stop()

    async def test_mexc_websocket_snapshot_updates_cache_and_status(self) -> None:
        cache = MarketDataCache()
        manager = WebSocketMarketDataManager(
            cache,
            connector_factory=lambda exchanges, reconnect_seconds, max_reconnect_attempts: [
                OneShotWebSocketConnector("mexc", "MEXC")
            ],
        )

        await manager.ensure_started(
            _live_websocket_config(
                enabled_connectors=("mexc",),
                websocket_exchanges=("mexc",),
            ),
            {"mexc": ("BTCUSDT",)},
        )
        await _wait_for_snapshot(cache)
        status = await manager.status()

        snapshots = await cache.get_all_snapshots()

        self.assertEqual(len(snapshots), 1)
        self.assertEqual(snapshots[0].exchange, "MEXC")
        self.assertEqual(snapshots[0].symbol, "BTCUSDT")
        self.assertEqual(status.active_exchanges, ("mexc",))
        self.assertTrue(status.connected["mexc"])
        self.assertEqual(status.connection_count["mexc"], 1)
        self.assertEqual(status.chunk_count["mexc"], 1)
        self.assertEqual(status.symbol_count["mexc"], 1)
        self.assertIsNotNone(status.last_message_at["mexc"])

        await manager.stop()

    async def test_websocket_manager_starts_all_configured_exchanges_with_case_insensitive_names(self) -> None:
        cache = MarketDataCache()
        display_names = {
            "binance": "Binance",
            "bybit": "Bybit",
            "okx": "OKX",
            "bitget": "Bitget",
            "gate": "Gate",
            "mexc": "MEXC",
        }
        factory_exchanges: list[tuple[str, ...]] = []

        def connector_factory(exchanges, reconnect_seconds, max_reconnect_attempts):
            factory_exchanges.append(exchanges)
            return [
                OneShotWebSocketConnector(exchange, display_names[exchange])
                for exchange in exchanges
            ]

        manager = WebSocketMarketDataManager(cache, connector_factory=connector_factory)

        await manager.ensure_started(
            _live_websocket_config(
                enabled_connectors=("binance", "bybit", "okx", "bitget", "gate", "mexc"),
                websocket_exchanges=("binance", "bybit", "okx", "bitget", "gate", "mexc"),
            ),
            {
                "Binance": ("BTCUSDT",),
                "bybit": ("BTCUSDT",),
                "OKX": ("BTCUSDT",),
                "Bitget": ("BTCUSDT",),
                "Gate": ("BTCUSDT",),
                "Mexc": ("BTCUSDT",),
            },
        )
        await _wait_for_snapshot_count(cache, 6)
        status = await manager.status()

        self.assertEqual(
            status.active_exchanges,
            ("binance", "bitget", "bybit", "gate", "mexc", "okx"),
        )
        self.assertEqual(
            factory_exchanges[0],
            ("binance", "bitget", "bybit", "gate", "mexc", "okx"),
        )
        self.assertTrue(all(status.connected.values()))
        self.assertEqual(status.symbol_count["mexc"], 1)

        await manager.stop()

    async def test_mexc_websocket_requires_configured_exchange_and_symbols(self) -> None:
        cache = MarketDataCache()
        manager = WebSocketMarketDataManager(
            cache,
            connector_factory=lambda exchanges, reconnect_seconds, max_reconnect_attempts: [
                OneShotWebSocketConnector("mexc", "MEXC")
            ],
        )

        await manager.ensure_started(
            _live_websocket_config(
                enabled_connectors=("mexc",),
                websocket_exchanges=("binance",),
            ),
            {"mexc": ("BTCUSDT",)},
        )
        status_without_websocket_exchange = await manager.status()
        await manager.ensure_started(
            _live_websocket_config(
                enabled_connectors=("mexc",),
                websocket_exchanges=("mexc",),
            ),
            {},
        )
        status_without_enabled_connector_symbols = await manager.status()

        self.assertEqual(status_without_websocket_exchange.active_exchanges, ())
        self.assertEqual(status_without_enabled_connector_symbols.active_exchanges, ())

    async def test_mexc_uses_one_all_tickers_chunk_for_large_symbol_lists(self) -> None:
        cache = MarketDataCache()
        manager = WebSocketMarketDataManager(
            cache,
            connector_factory=lambda exchanges, reconnect_seconds, max_reconnect_attempts: [
                OneShotWebSocketConnector("mexc", "MEXC")
            ],
        )

        await manager.ensure_started(
            _live_websocket_config(
                enabled_connectors=("mexc",),
                websocket_exchanges=("mexc",),
                max_symbols_per_connection=2,
            ),
            {"mexc": ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT")},
        )
        await _wait_for_snapshot(cache)
        status = await manager.status()

        self.assertEqual(status.chunk_count["mexc"], 1)
        self.assertEqual(status.connection_count["mexc"], 1)
        self.assertEqual(status.symbol_count["mexc"], 4)

        await manager.stop()

    async def test_small_symbol_list_uses_one_websocket_chunk(self) -> None:
        cache = MarketDataCache()
        manager = WebSocketMarketDataManager(
            cache,
            connector_factory=lambda exchanges, reconnect_seconds, max_reconnect_attempts: [
                OneShotWebSocketConnector("binance", "Binance")
            ],
        )

        await manager.ensure_started(
            _live_websocket_config(max_symbols_per_connection=50),
            {"binance": ("BTCUSDT", "ETHUSDT")},
        )
        await _wait_for_snapshot_count(cache, 1)
        status = await manager.status()

        self.assertEqual(status.chunk_count["binance"], 1)
        self.assertEqual(status.connection_count["binance"], 1)
        self.assertEqual(status.symbol_count["binance"], 2)
        self.assertTrue(status.connected["binance"])

        await manager.stop()

    async def test_large_symbol_list_uses_multiple_websocket_chunks(self) -> None:
        cache = MarketDataCache()
        manager = WebSocketMarketDataManager(
            cache,
            connector_factory=lambda exchanges, reconnect_seconds, max_reconnect_attempts: [
                OneShotWebSocketConnector("binance", "Binance")
            ],
        )

        await manager.ensure_started(
            _live_websocket_config(max_symbols_per_connection=2),
            {"binance": ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT")},
        )
        await _wait_for_snapshot_count(cache, 3)
        status = await manager.status()

        self.assertEqual(status.chunk_count["binance"], 3)
        self.assertEqual(status.connection_count["binance"], 3)
        self.assertEqual(status.symbol_count["binance"], 5)
        self.assertTrue(status.connected["binance"])

        await manager.stop()

    async def test_failed_websocket_chunk_retries_without_crashing_manager(self) -> None:
        cache = MarketDataCache()
        connector = FlakyWebSocketConnector("binance", "Binance")
        manager = WebSocketMarketDataManager(
            cache,
            connector_factory=lambda exchanges, reconnect_seconds, max_reconnect_attempts: [
                connector
            ],
        )

        await manager.ensure_started(
            _live_websocket_config(max_reconnect_attempts=2),
            {"binance": ("BTCUSDT",)},
        )
        await _wait_for_snapshot(cache)
        status = await manager.status()

        self.assertEqual(connector.listen_calls, 2)
        self.assertTrue(status.connected["binance"])
        self.assertEqual(status.connection_count["binance"], 1)
        self.assertEqual(status.reconnect_count["binance"], 1)
        self.assertIsNone(status.last_error_by_exchange["binance"])

        await manager.stop()

    async def test_websocket_disabled_stops_running_tasks(self) -> None:
        cache = MarketDataCache()
        manager = WebSocketMarketDataManager(
            cache,
            connector_factory=lambda exchanges, reconnect_seconds, max_reconnect_attempts: [
                OneShotWebSocketConnector("binance", "Binance")
            ],
        )

        await manager.ensure_started(
            _live_websocket_config(),
            {"binance": ("BTCUSDT",)},
        )
        await _wait_for_snapshot(cache)
        await manager.ensure_started(
            _live_rest_config(),
            {"binance": ("BTCUSDT",)},
        )
        status = await manager.status()

        self.assertEqual(status.active_exchanges, ())
        self.assertEqual(status.connected, {})


class OneShotWebSocketConnector(PublicWebSocketConnector):
    data_source = "test_websocket"

    def __init__(self, name: str, exchange_name: str) -> None:
        super().__init__(reconnect_seconds=1)
        self.name = name
        self.exchange_name = exchange_name

    async def listen(
        self,
        symbols,
        on_snapshot,
        on_connection_status,
        stop_event,
    ) -> None:
        await on_connection_status(self.name, True, None)
        await on_snapshot(
            MarketSnapshot(
                exchange=self.exchange_name,
                symbol=symbols[0],
                best_bid=100.0,
                best_bid_size=1.0,
                best_ask=101.0,
                best_ask_size=1.0,
                volume_24h_usd=0,
                funding_rate_percent=0,
                next_funding_time=None,
                timestamp=datetime.now(timezone.utc),
                source="websocket",
            )
        )
        await stop_event.wait()


class FlakyWebSocketConnector(PublicWebSocketConnector):
    data_source = "test_websocket"

    def __init__(self, name: str, exchange_name: str) -> None:
        super().__init__(reconnect_seconds=1)
        self.reconnect_seconds = 0
        self.name = name
        self.exchange_name = exchange_name
        self.listen_calls = 0

    async def listen(
        self,
        symbols,
        on_snapshot,
        on_connection_status,
        stop_event,
    ) -> None:
        self.listen_calls += 1
        if self.listen_calls == 1:
            raise RuntimeError("temporary websocket failure")

        await on_connection_status(self.name, True, None)
        await on_snapshot(
            MarketSnapshot(
                exchange=self.exchange_name,
                symbol=symbols[0],
                best_bid=100.0,
                best_bid_size=1.0,
                best_ask=101.0,
                best_ask_size=1.0,
                volume_24h_usd=0,
                funding_rate_percent=0,
                next_funding_time=None,
                timestamp=datetime.now(timezone.utc),
                source="websocket",
            )
        )
        await stop_event.wait()


async def _wait_for_snapshot(cache: MarketDataCache) -> None:
    await _wait_for_snapshot_count(cache, 1)


async def _wait_for_snapshot_count(cache: MarketDataCache, count: int) -> None:
    for _ in range(20):
        if await cache.snapshot_count() >= count:
            return
        await asyncio.sleep(0.01)
    raise AssertionError("Timed out waiting for websocket snapshot")


def _live_websocket_config(
    enabled_connectors: tuple[str, ...] = ("binance",),
    websocket_exchanges: tuple[str, ...] = ("binance",),
    max_symbols_per_connection: int = 50,
    max_reconnect_attempts: int = 0,
):
    return _load_config(
        f"""
data_source_mode: live
enabled_connectors:
{_yaml_list(enabled_connectors)}
symbol_allowlist:
  - BTCUSDT
market_data:
  mode: websocket
  websocket:
    enabled: true
    exchanges:
{_yaml_list(websocket_exchanges, indent=6)}
    reconnect_seconds: 1
    stale_after_seconds: 20
    max_symbols_per_connection: {max_symbols_per_connection}
    connection_start_delay_seconds: 0
    max_reconnect_attempts: {max_reconnect_attempts}
"""
    )


def _live_rest_config():
    return _load_config(
        """
data_source_mode: live
enabled_connectors:
  - binance
symbol_allowlist:
  - BTCUSDT
market_data:
  mode: rest
  websocket:
    enabled: false
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


def _yaml_list(values: tuple[str, ...], indent: int = 2) -> str:
    prefix = " " * indent
    return "\n".join(f"{prefix}- {value}" for value in values)


if __name__ == "__main__":
    unittest.main()
