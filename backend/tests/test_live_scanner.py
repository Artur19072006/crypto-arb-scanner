import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from app.connectors.base import ExchangeConnector
from app.connectors.registry import build_connector_registry
from app.core.config import load_app_config
from app.domain.models import MarketSnapshot
from app.services.live_scanner import refresh_mock_scanner_once
from app.services.market_data_cache import MarketDataCache
from app.services.opportunity_store import OpportunityStore


class LiveScannerTests(unittest.IsolatedAsyncioTestCase):
    async def test_refresh_mock_scanner_uses_registry_and_updates_state(self) -> None:
        cache = MarketDataCache()
        store = OpportunityStore()
        registry = build_connector_registry("mock")

        await refresh_mock_scanner_once(cache=cache, store=store, registry=registry)

        snapshots = await cache.get_all_snapshots()
        opportunities = await store.get_all_opportunities()

        self.assertEqual(await cache.snapshot_count(), 6)
        self.assertGreaterEqual(await store.opportunity_count(), 2)
        self.assertIsNotNone(await store.get_last_updated())
        self.assertEqual({snapshot.exchange for snapshot in snapshots}, {
            "Binance",
            "Bybit",
            "OKX",
            "Bitget",
        })
        self.assertTrue(all(opportunity.long_exchange != opportunity.short_exchange for opportunity in opportunities))
        self.assertTrue(
            all(
                opportunity.depth_check is None
                or opportunity.depth_check.depth_status == "Unknown"
                for opportunity in opportunities
            )
        )

    async def test_rest_market_data_mode_uses_rest_snapshots(self) -> None:
        cache = MarketDataCache()
        store = OpportunityStore()
        registry = _live_registry(
            binance_snapshot=_snapshot("Binance", bid=99.0, ask=100.0),
            bybit_snapshot=_snapshot("Bybit", bid=101.0, ask=102.0),
        )

        await refresh_mock_scanner_once(
            cache=cache,
            store=store,
            registry=registry,
            websocket_manager=NoopWebSocketManager(),
            config=_live_config(market_data_mode="rest", websocket_enabled=False),
        )

        opportunities = await store.get_all_opportunities()

        self.assertEqual(len(opportunities), 1)
        self.assertEqual(opportunities[0].ask_price, 100.0)
        self.assertEqual(opportunities[0].bid_price, 101.0)

    async def test_rest_market_data_mode_can_use_bitget_snapshots(self) -> None:
        cache = MarketDataCache()
        store = OpportunityStore()
        registry = _live_registry(
            binance_snapshot=_snapshot("Binance", bid=100.0, ask=101.0),
            bybit_snapshot=_snapshot("Bybit", bid=101.0, ask=102.0),
            bitget_snapshot=_snapshot("Bitget", bid=98.0, ask=99.0),
        )

        await refresh_mock_scanner_once(
            cache=cache,
            store=store,
            registry=registry,
            websocket_manager=NoopWebSocketManager(),
            config=_live_config(
                market_data_mode="rest",
                websocket_enabled=False,
                include_bitget=True,
            ),
        )

        opportunities = await store.get_all_opportunities()

        self.assertEqual(len(opportunities), 1)
        self.assertEqual(opportunities[0].long_exchange, "Bitget")
        self.assertEqual(opportunities[0].short_exchange, "Bybit")
        self.assertEqual(opportunities[0].ask_price, 99.0)
        self.assertEqual(opportunities[0].bid_price, 101.0)

    async def test_websocket_mode_prefers_fresh_websocket_top_of_book(self) -> None:
        cache = MarketDataCache()
        store = OpportunityStore()
        registry = _live_registry(
            binance_snapshot=_snapshot("Binance", bid=99.0, ask=100.0),
            bybit_snapshot=_snapshot("Bybit", bid=101.0, ask=102.0),
        )
        await cache.update_snapshots(
            [
                _snapshot(
                    "Binance",
                    bid=89.0,
                    ask=90.0,
                    volume_24h_usd=0,
                    funding_rate_percent=0,
                    source="websocket",
                )
            ],
            source="websocket",
        )

        await refresh_mock_scanner_once(
            cache=cache,
            store=store,
            registry=registry,
            websocket_manager=NoopWebSocketManager(),
            config=_live_config(market_data_mode="websocket", websocket_enabled=True),
        )

        opportunities = await store.get_all_opportunities()

        self.assertEqual(len(opportunities), 1)
        self.assertEqual(opportunities[0].ask_price, 90.0)
        self.assertEqual(opportunities[0].bid_price, 101.0)
        self.assertEqual(opportunities[0].volume_24h_usd, 1_000_000)

    async def test_websocket_mode_falls_back_to_rest_when_websocket_is_stale(self) -> None:
        cache = MarketDataCache()
        store = OpportunityStore()
        registry = _live_registry(
            binance_snapshot=_snapshot("Binance", bid=99.0, ask=100.0),
            bybit_snapshot=_snapshot("Bybit", bid=101.0, ask=102.0),
        )
        await cache.update_snapshots(
            [
                _snapshot(
                    "Binance",
                    bid=89.0,
                    ask=90.0,
                    timestamp=datetime.now(timezone.utc) - timedelta(minutes=5),
                    source="websocket",
                )
            ],
            source="websocket",
        )

        await refresh_mock_scanner_once(
            cache=cache,
            store=store,
            registry=registry,
            websocket_manager=NoopWebSocketManager(),
            config=_live_config(market_data_mode="websocket", websocket_enabled=True),
        )

        opportunities = await store.get_all_opportunities()

        self.assertEqual(len(opportunities), 1)
        self.assertEqual(opportunities[0].ask_price, 100.0)
        self.assertEqual(opportunities[0].bid_price, 101.0)

    async def test_websocket_mode_can_use_fresh_okx_top_of_book(self) -> None:
        cache = MarketDataCache()
        store = OpportunityStore()
        registry = _live_registry(
            binance_snapshot=_snapshot("Binance", bid=99.0, ask=100.0),
            bybit_snapshot=_snapshot("Bybit", bid=101.0, ask=102.0),
            okx_snapshot=_snapshot("OKX", bid=98.0, ask=103.0),
        )
        await cache.update_snapshots(
            [
                _snapshot(
                    "OKX",
                    bid=89.0,
                    ask=90.0,
                    volume_24h_usd=0,
                    funding_rate_percent=0,
                    source="websocket",
                )
            ],
            source="websocket",
        )

        await refresh_mock_scanner_once(
            cache=cache,
            store=store,
            registry=registry,
            websocket_manager=NoopWebSocketManager(),
            config=_live_config(
                market_data_mode="websocket",
                websocket_enabled=True,
                include_okx=True,
            ),
        )

        opportunities = await store.get_all_opportunities()

        self.assertEqual(len(opportunities), 1)
        self.assertEqual(opportunities[0].long_exchange, "OKX")
        self.assertEqual(opportunities[0].short_exchange, "Bybit")
        self.assertEqual(opportunities[0].ask_price, 90.0)
        self.assertEqual(opportunities[0].bid_price, 101.0)
        self.assertEqual(opportunities[0].volume_24h_usd, 1_000_000)

    async def test_websocket_mode_falls_back_to_okx_rest_when_okx_websocket_is_stale(self) -> None:
        cache = MarketDataCache()
        store = OpportunityStore()
        registry = _live_registry(
            binance_snapshot=_snapshot("Binance", bid=94.0, ask=95.0),
            bybit_snapshot=_snapshot("Bybit", bid=101.0, ask=102.0),
            okx_snapshot=_snapshot("OKX", bid=98.0, ask=100.0),
        )
        await cache.update_snapshots(
            [
                _snapshot(
                    "OKX",
                    bid=89.0,
                    ask=90.0,
                    timestamp=datetime.now(timezone.utc) - timedelta(minutes=5),
                    source="websocket",
                )
            ],
            source="websocket",
        )

        await refresh_mock_scanner_once(
            cache=cache,
            store=store,
            registry=registry,
            websocket_manager=NoopWebSocketManager(),
            config=_live_config(
                market_data_mode="websocket",
                websocket_enabled=True,
                include_okx=True,
            ),
        )

        opportunities = await store.get_all_opportunities()

        self.assertEqual(len(opportunities), 1)
        self.assertEqual(opportunities[0].long_exchange, "Binance")
        self.assertEqual(opportunities[0].short_exchange, "Bybit")
        self.assertEqual(opportunities[0].ask_price, 95.0)
        self.assertEqual(opportunities[0].bid_price, 101.0)


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


def _live_registry(
    binance_snapshot: MarketSnapshot,
    bybit_snapshot: MarketSnapshot,
    okx_snapshot: MarketSnapshot | None = None,
    bitget_snapshot: MarketSnapshot | None = None,
):
    from app.connectors.registry import ConnectorRegistry

    registry = ConnectorRegistry()
    registry.register(StaticSnapshotConnector("binance", binance_snapshot))
    registry.register(StaticSnapshotConnector("bybit", bybit_snapshot))
    if okx_snapshot is not None:
        registry.register(StaticSnapshotConnector("okx", okx_snapshot))
    if bitget_snapshot is not None:
        registry.register(StaticSnapshotConnector("bitget", bitget_snapshot))
    return registry


def _live_config(
    market_data_mode: str,
    websocket_enabled: bool,
    include_okx: bool = False,
    include_bitget: bool = False,
):
    connectors = ["binance", "bybit"]
    exchanges = ["Binance", "Bybit"]
    websocket_exchanges = ["binance", "bybit"]
    if include_okx:
        connectors.append("okx")
        exchanges.append("OKX")
        websocket_exchanges.append("okx")
    if include_bitget:
        connectors.append("bitget")
        exchanges.append("Bitget")

    with TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        config_path = root / "config.yaml"
        config_path.write_text(
            f"""
data_source_mode: live
enabled_connectors:
{_yaml_list(connectors)}
max_symbols: 1
symbol_allowlist:
  - BTCUSDT
filters:
  min_raw_spread: 0
  min_net_spread: -10
  min_volume_24h_usd: 0
  enabled_exchanges:
{_yaml_list(exchanges, indent=4)}
market_data:
  mode: {market_data_mode}
  websocket:
    enabled: {str(websocket_enabled).lower()}
    exchanges:
{_yaml_list(websocket_exchanges, indent=6)}
    reconnect_seconds: 1
    stale_after_seconds: 20
""",
            encoding="utf-8",
        )
        return load_app_config(
            config_path=config_path,
            example_path=root / "config.example.yaml",
        )


def _yaml_list(values: list[str], indent: int = 2) -> str:
    prefix = " " * indent
    return "\n".join(f"{prefix}- {value}" for value in values)


def _snapshot(
    exchange: str,
    bid: float,
    ask: float,
    volume_24h_usd: float = 1_000_000,
    funding_rate_percent: float = 0.01,
    timestamp: datetime | None = None,
    source: str = "rest",
) -> MarketSnapshot:
    return MarketSnapshot(
        exchange=exchange,
        symbol="BTCUSDT",
        best_bid=bid,
        best_bid_size=10.0,
        best_ask=ask,
        best_ask_size=10.0,
        volume_24h_usd=volume_24h_usd,
        funding_rate_percent=funding_rate_percent,
        next_funding_time=None,
        timestamp=timestamp or datetime.now(timezone.utc),
        source=source,
    )


if __name__ == "__main__":
    unittest.main()
