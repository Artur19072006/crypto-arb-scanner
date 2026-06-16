import unittest

from app.connectors.registry import build_connector_registry
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


if __name__ == "__main__":
    unittest.main()
