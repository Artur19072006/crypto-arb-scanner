import unittest
from datetime import datetime, timezone

from app.domain.models import ExchangeFees, MarketSnapshot, ScannerFilters
from app.services.spread_engine import calculate_opportunities


class SpreadEngineTests(unittest.TestCase):
    def test_calculates_binance_bybit_bid_ask_spread_and_net_after_round_trip_fees(self) -> None:
        opportunities = calculate_opportunities(
            snapshots=[
                self._snapshot("Binance", "BTCUSDT", bid=99.5, ask=100.0),
                self._snapshot("Bybit", "BTCUSDT", bid=101.0, ask=101.5),
            ],
            fees_by_exchange={
                "Binance": ExchangeFees(maker_percent=0.02, taker_percent=0.05),
                "Bybit": ExchangeFees(maker_percent=0.02, taker_percent=0.055),
            },
        )

        self.assertEqual(len(opportunities), 1)
        opportunity = opportunities[0]
        self.assertEqual(opportunity.long_exchange, "Binance")
        self.assertEqual(opportunity.short_exchange, "Bybit")
        self.assertEqual(opportunity.raw_spread_percent, 1.0)
        self.assertEqual(opportunity.estimated_net_spread_percent, 0.79)
        self.assertEqual(opportunity.volume_24h_usd, 1_000_000)
        self.assertEqual(opportunity.liquidity_status, "OK")

    def test_applies_minimum_filters(self) -> None:
        opportunities = calculate_opportunities(
            snapshots=[
                self._snapshot("Binance", "ETHUSDT", bid=99.5, ask=100.0),
                self._snapshot("Bybit", "ETHUSDT", bid=100.3, ask=100.4),
            ],
            fees_by_exchange={
                "Binance": ExchangeFees(maker_percent=0.02, taker_percent=0.05),
                "Bybit": ExchangeFees(maker_percent=0.02, taker_percent=0.05),
            },
            filters=ScannerFilters(min_raw_spread=0.5),
        )

        self.assertEqual(opportunities, [])

    def test_applies_exchange_filter_to_both_sides(self) -> None:
        opportunities = calculate_opportunities(
            snapshots=[
                self._snapshot("Binance", "SOLUSDT", bid=99.5, ask=100.0),
                self._snapshot("Bybit", "SOLUSDT", bid=101.0, ask=101.5),
            ],
            fees_by_exchange={
                "Binance": ExchangeFees(maker_percent=0.02, taker_percent=0.05),
                "Bybit": ExchangeFees(maker_percent=0.02, taker_percent=0.05),
            },
            filters=ScannerFilters(exchanges=("Binance",)),
        )

        self.assertEqual(opportunities, [])

    def test_exchange_filter_limits_snapshots_before_spread_calculation(self) -> None:
        opportunities = calculate_opportunities(
            snapshots=[
                self._snapshot("OKX", "SOLUSDT", bid=98.0, ask=90.0),
                self._snapshot("Binance", "SOLUSDT", bid=99.5, ask=100.0),
                self._snapshot("Bybit", "SOLUSDT", bid=101.0, ask=101.5),
            ],
            fees_by_exchange={
                "Binance": ExchangeFees(maker_percent=0.02, taker_percent=0.05),
                "Bybit": ExchangeFees(maker_percent=0.02, taker_percent=0.05),
                "OKX": ExchangeFees(maker_percent=0.02, taker_percent=0.05),
            },
            filters=ScannerFilters(exchanges=("Binance", "Bybit")),
        )

        self.assertEqual(len(opportunities), 1)
        self.assertEqual(opportunities[0].long_exchange, "Binance")
        self.assertEqual(opportunities[0].short_exchange, "Bybit")
        self.assertEqual(opportunities[0].raw_spread_percent, 1.0)

    @staticmethod
    def _snapshot(
        exchange: str,
        symbol: str,
        bid: float,
        ask: float,
    ) -> MarketSnapshot:
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


if __name__ == "__main__":
    unittest.main()
