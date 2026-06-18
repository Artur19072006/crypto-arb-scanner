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
        self.assertEqual(opportunity.estimated_fee_percent, 0.21)
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

    def test_calculates_best_opportunity_across_binance_bybit_and_okx(self) -> None:
        opportunities = calculate_opportunities(
            snapshots=[
                self._snapshot("Binance", "BTCUSDT", bid=100.0, ask=101.0, volume=2_000_000),
                self._snapshot("Bybit", "BTCUSDT", bid=103.0, ask=104.0, volume=1_500_000),
                self._snapshot("OKX", "BTCUSDT", bid=99.0, ask=100.0, volume=750_000),
            ],
            fees_by_exchange={
                "Binance": ExchangeFees(maker_percent=0.02, taker_percent=0.05),
                "Bybit": ExchangeFees(maker_percent=0.02, taker_percent=0.055),
                "OKX": ExchangeFees(maker_percent=0.02, taker_percent=0.05),
            },
        )

        self.assertEqual(len(opportunities), 1)
        opportunity = opportunities[0]
        self.assertEqual(opportunity.long_exchange, "OKX")
        self.assertEqual(opportunity.short_exchange, "Bybit")
        self.assertEqual(opportunity.raw_spread_percent, 3.0)
        self.assertEqual(opportunity.volume_24h_usd, 750_000)

    def test_calculates_opportunity_using_bitget_snapshot(self) -> None:
        opportunities = calculate_opportunities(
            snapshots=[
                self._snapshot("Bitget", "BTCUSDT", bid=99.0, ask=100.0, volume=900_000),
                self._snapshot("Bybit", "BTCUSDT", bid=102.0, ask=103.0, volume=1_500_000),
            ],
            fees_by_exchange={
                "Bitget": ExchangeFees(maker_percent=0.02, taker_percent=0.06),
                "Bybit": ExchangeFees(maker_percent=0.02, taker_percent=0.055),
            },
        )

        self.assertEqual(len(opportunities), 1)
        opportunity = opportunities[0]
        self.assertEqual(opportunity.long_exchange, "Bitget")
        self.assertEqual(opportunity.short_exchange, "Bybit")
        self.assertEqual(opportunity.raw_spread_percent, 2.0)
        self.assertEqual(opportunity.estimated_fee_percent, 0.23)
        self.assertEqual(opportunity.estimated_net_spread_percent, 1.77)

    def test_calculates_opportunity_using_gate_snapshot(self) -> None:
        opportunities = calculate_opportunities(
            snapshots=[
                self._snapshot("Gate", "BTCUSDT", bid=99.0, ask=100.0, volume=900_000),
                self._snapshot("Bybit", "BTCUSDT", bid=102.0, ask=103.0, volume=1_500_000),
            ],
            fees_by_exchange={
                "Gate": ExchangeFees(maker_percent=0.02, taker_percent=0.05),
                "Bybit": ExchangeFees(maker_percent=0.02, taker_percent=0.055),
            },
        )

        self.assertEqual(len(opportunities), 1)
        opportunity = opportunities[0]
        self.assertEqual(opportunity.long_exchange, "Gate")
        self.assertEqual(opportunity.short_exchange, "Bybit")
        self.assertEqual(opportunity.raw_spread_percent, 2.0)
        self.assertEqual(opportunity.estimated_fee_percent, 0.21)
        self.assertEqual(opportunity.estimated_net_spread_percent, 1.79)

    def test_calculates_opportunity_using_mexc_snapshot(self) -> None:
        opportunities = calculate_opportunities(
            snapshots=[
                self._snapshot("MEXC", "BTCUSDT", bid=99.0, ask=100.0, volume=900_000),
                self._snapshot("Bybit", "BTCUSDT", bid=102.0, ask=103.0, volume=1_500_000),
            ],
            fees_by_exchange={
                "MEXC": ExchangeFees(maker_percent=0.02, taker_percent=0.06),
                "Bybit": ExchangeFees(maker_percent=0.02, taker_percent=0.055),
            },
        )

        self.assertEqual(len(opportunities), 1)
        opportunity = opportunities[0]
        self.assertEqual(opportunity.long_exchange, "MEXC")
        self.assertEqual(opportunity.short_exchange, "Bybit")
        self.assertEqual(opportunity.raw_spread_percent, 2.0)
        self.assertEqual(opportunity.estimated_fee_percent, 0.23)
        self.assertEqual(opportunity.estimated_net_spread_percent, 1.77)

    @staticmethod
    def _snapshot(
        exchange: str,
        symbol: str,
        bid: float,
        ask: float,
        volume: float = 1_000_000,
    ) -> MarketSnapshot:
        return MarketSnapshot(
            exchange=exchange,
            symbol=symbol,
            best_bid=bid,
            best_bid_size=10.0,
            best_ask=ask,
            best_ask_size=10.0,
            volume_24h_usd=volume,
            funding_rate_percent=0.01,
            next_funding_time=None,
            timestamp=datetime.now(timezone.utc),
        )


if __name__ == "__main__":
    unittest.main()
