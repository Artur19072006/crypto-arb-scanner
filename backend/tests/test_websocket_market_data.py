import asyncio
import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from app.connectors.websocket import PublicWebSocketConnector
from app.core.config import load_app_config
from app.domain.models import MarketSnapshot
from app.services.market_data_cache import MarketDataCache
from app.services.websocket_market_data import WebSocketMarketDataManager


class WebSocketMarketDataManagerTests(unittest.IsolatedAsyncioTestCase):
    async def test_websocket_snapshots_update_cache_and_status(self) -> None:
        cache = MarketDataCache()
        manager = WebSocketMarketDataManager(
            cache,
            connector_factory=lambda exchanges, reconnect_seconds: [
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
        self.assertIsNotNone(status.last_update_at)

        await manager.stop()
        stopped_status = await manager.status()
        self.assertEqual(stopped_status.active_exchanges, ())
        self.assertEqual(stopped_status.connected, {})

    async def test_okx_websocket_snapshot_updates_cache_and_status(self) -> None:
        cache = MarketDataCache()
        manager = WebSocketMarketDataManager(
            cache,
            connector_factory=lambda exchanges, reconnect_seconds: [
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

    async def test_websocket_disabled_stops_running_tasks(self) -> None:
        cache = MarketDataCache()
        manager = WebSocketMarketDataManager(
            cache,
            connector_factory=lambda exchanges, reconnect_seconds: [
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


async def _wait_for_snapshot(cache: MarketDataCache) -> None:
    for _ in range(20):
        if await cache.snapshot_count():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("Timed out waiting for websocket snapshot")


def _live_websocket_config(
    enabled_connectors: tuple[str, ...] = ("binance",),
    websocket_exchanges: tuple[str, ...] = ("binance",),
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
