import unittest
from datetime import datetime, timezone

from app.domain.models import ArbitrageOpportunity, MarketSnapshot
from app.services.market_data_cache import MarketDataCache
from app.services.opportunity_store import OpportunityStore


class MarketDataCacheTests(unittest.IsolatedAsyncioTestCase):
    async def test_update_snapshots_replaces_latest_by_symbol_and_exchange(self) -> None:
        cache = MarketDataCache()

        await cache.update_snapshots([
            _snapshot("Binance", "BTCUSDT", bid=100.0, ask=101.0),
            _snapshot("Bybit", "BTCUSDT", bid=102.0, ask=103.0),
        ])
        await cache.update_snapshots([
            _snapshot("Binance", "BTCUSDT", bid=105.0, ask=106.0),
        ])

        snapshots = await cache.get_all_snapshots()

        self.assertEqual(await cache.snapshot_count(), 2)
        self.assertEqual(
            {(snapshot.exchange, snapshot.best_bid) for snapshot in snapshots},
            {("Binance", 105.0), ("Bybit", 102.0)},
        )


class OpportunityStoreTests(unittest.IsolatedAsyncioTestCase):
    async def test_update_opportunities_replaces_list_and_sets_timestamp(self) -> None:
        store = OpportunityStore()
        updated_at = datetime(2026, 1, 1, tzinfo=timezone.utc)

        await store.update_opportunities([
            _opportunity("BTCUSDT", raw_spread=0.2),
        ])
        await store.update_opportunities([
            _opportunity("ETHUSDT", raw_spread=0.3),
            _opportunity("SOLUSDT", raw_spread=0.4),
        ], updated_at=updated_at)

        opportunities = await store.get_all_opportunities()

        self.assertEqual(await store.opportunity_count(), 2)
        self.assertEqual(await store.get_last_updated(), updated_at)
        self.assertEqual([opportunity.symbol for opportunity in opportunities], [
            "ETHUSDT",
            "SOLUSDT",
        ])


def _snapshot(exchange: str, symbol: str, bid: float, ask: float) -> MarketSnapshot:
    return MarketSnapshot(
        exchange=exchange,
        symbol=symbol,
        best_bid=bid,
        best_bid_size=10.0,
        best_ask=ask,
        best_ask_size=10.0,
        volume_24h_usd=1_000_000,
        funding_rate_percent=0.01,
        next_funding_time=None,
        timestamp=datetime.now(timezone.utc),
    )


def _opportunity(symbol: str, raw_spread: float) -> ArbitrageOpportunity:
    return ArbitrageOpportunity(
        symbol=symbol,
        long_exchange="Binance",
        short_exchange="Bybit",
        ask_price=100.0,
        bid_price=101.0,
        raw_spread_percent=raw_spread,
        estimated_net_spread_percent=raw_spread - 0.2,
        volume_24h_usd=1_000_000,
        best_ask_size=10.0,
        best_bid_size=10.0,
        long_funding_rate_percent=0.01,
        short_funding_rate_percent=0.02,
        funding_rate_difference_percent=0.01,
        next_funding_time=None,
        funding_impact="Good",
        liquidity_status="OK",
        timestamp=datetime.now(timezone.utc),
    )


if __name__ == "__main__":
    unittest.main()
