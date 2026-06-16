import unittest
from datetime import datetime, timedelta, timezone

from app.api.routes import (
    _build_filters,
    _build_opportunities_response,
    _parse_exchanges,
)
from app.domain.models import ArbitrageOpportunity, ScannerFilters


class ApiFilterTests(unittest.TestCase):
    def test_parse_exchanges_accepts_repeated_and_comma_separated_values(self) -> None:
        exchanges = _parse_exchanges(["Binance,Bybit", "OKX", "Binance"])

        self.assertEqual(exchanges, ("Binance", "Bybit", "OKX"))

    def test_build_filters_uses_query_values_when_provided(self) -> None:
        filters = _build_filters(
            min_raw_spread=0.25,
            min_net_spread=0.05,
            min_volume_24h_usd=1_000_000,
            exchanges=["Binance", "Bybit"],
        )

        self.assertEqual(filters.min_raw_spread, 0.25)
        self.assertEqual(filters.min_net_spread, 0.05)
        self.assertEqual(filters.min_volume_24h_usd, 1_000_000)
        self.assertEqual(filters.exchanges, ("Binance", "Bybit"))

    def test_build_filters_accepts_decimal_comma_values(self) -> None:
        filters = _build_filters(
            min_raw_spread="0,25",
            min_net_spread="-0,5",
            min_volume_24h_usd="1000000,50",
            exchanges=["Binance"],
        )

        self.assertEqual(filters.min_raw_spread, 0.25)
        self.assertEqual(filters.min_net_spread, -0.5)
        self.assertEqual(filters.min_volume_24h_usd, 1_000_000.50)
        self.assertEqual(filters.exchanges, ("Binance",))

    def test_build_filters_accepts_decimal_dot_values(self) -> None:
        filters = _build_filters(
            min_raw_spread="0.10",
            min_net_spread="-1",
            min_volume_24h_usd="0",
        )

        self.assertEqual(filters.min_raw_spread, 0.10)
        self.assertEqual(filters.min_net_spread, -1)
        self.assertEqual(filters.min_volume_24h_usd, 0)

    def test_opportunities_response_sorts_by_raw_spread_desc(self) -> None:
        response = _build_opportunities_response(
            stored_opportunities=_opportunities(),
            queryable_opportunities=_opportunities(),
            filters=ScannerFilters(exchanges=("Binance", "Bybit")),
            sort_by="raw_spread",
            sort_dir="desc",
        )

        self.assertEqual(
            [opportunity.symbol for opportunity in response.opportunities],
            ["SOLUSDT", "BTCUSDT", "ETHUSDT"],
        )
        self.assertEqual(response.sort_by, "raw_spread")
        self.assertEqual(response.sort_dir, "desc")

    def test_opportunities_response_sorts_by_net_spread_desc_by_default(self) -> None:
        response = _build_opportunities_response(
            stored_opportunities=_opportunities(),
            queryable_opportunities=_opportunities(),
            filters=ScannerFilters(exchanges=("Binance", "Bybit")),
        )

        self.assertEqual(
            [opportunity.symbol for opportunity in response.opportunities],
            ["BTCUSDT", "SOLUSDT", "ETHUSDT"],
        )
        self.assertEqual(response.sort_by, "net_spread")
        self.assertEqual(response.sort_dir, "desc")

    def test_opportunities_response_sorts_by_volume_desc(self) -> None:
        response = _build_opportunities_response(
            stored_opportunities=_opportunities(),
            queryable_opportunities=_opportunities(),
            filters=ScannerFilters(exchanges=("Binance", "Bybit")),
            sort_by="volume_24h",
            sort_dir="desc",
        )

        self.assertEqual(
            [opportunity.symbol for opportunity in response.opportunities],
            ["ETHUSDT", "BTCUSDT", "SOLUSDT"],
        )

    def test_opportunities_response_applies_limit(self) -> None:
        response = _build_opportunities_response(
            stored_opportunities=_opportunities(),
            queryable_opportunities=_opportunities(),
            filters=ScannerFilters(exchanges=("Binance", "Bybit")),
            sort_by="net_spread",
            sort_dir="desc",
            limit=2,
        )

        self.assertEqual(response.returned_count, 2)
        self.assertEqual(response.limit, 2)
        self.assertEqual(
            [opportunity.symbol for opportunity in response.opportunities],
            ["BTCUSDT", "SOLUSDT"],
        )

    def test_opportunities_response_filters_by_symbol_query(self) -> None:
        response = _build_opportunities_response(
            stored_opportunities=_opportunities(),
            queryable_opportunities=_opportunities(),
            filters=ScannerFilters(exchanges=("Binance", "Bybit")),
            symbol_query="SOL",
        )

        self.assertEqual(response.filtered_opportunity_count, 1)
        self.assertEqual(response.returned_count, 1)
        self.assertEqual(response.opportunities[0].symbol, "SOLUSDT")

    def test_opportunities_response_keeps_existing_filters(self) -> None:
        response = _build_opportunities_response(
            stored_opportunities=_opportunities(),
            queryable_opportunities=_opportunities(),
            filters=ScannerFilters(
                min_raw_spread=0.30,
                min_net_spread=0.10,
                min_volume_24h_usd=1_000_000,
                exchanges=("Binance", "Bybit"),
            ),
        )

        self.assertEqual(response.filtered_opportunity_count, 1)
        self.assertEqual(response.opportunities[0].symbol, "BTCUSDT")


def _opportunities() -> list[ArbitrageOpportunity]:
    base_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return [
        _opportunity(
            "BTCUSDT",
            raw_spread=0.45,
            net_spread=0.25,
            volume=2_000_000,
            timestamp=base_time,
        ),
        _opportunity(
            "ETHUSDT",
            raw_spread=0.20,
            net_spread=0.05,
            volume=3_000_000,
            timestamp=base_time + timedelta(seconds=1),
        ),
        _opportunity(
            "SOLUSDT",
            raw_spread=0.60,
            net_spread=0.15,
            volume=500_000,
            timestamp=base_time + timedelta(seconds=2),
        ),
    ]


def _opportunity(
    symbol: str,
    raw_spread: float,
    net_spread: float,
    volume: float,
    timestamp: datetime,
) -> ArbitrageOpportunity:
    return ArbitrageOpportunity(
        symbol=symbol,
        long_exchange="Binance",
        short_exchange="Bybit",
        ask_price=100.0,
        bid_price=101.0,
        raw_spread_percent=raw_spread,
        estimated_net_spread_percent=net_spread,
        estimated_fee_percent=max(raw_spread - net_spread, 0),
        volume_24h_usd=volume,
        best_ask_size=10.0,
        best_bid_size=10.0,
        long_funding_rate_percent=0.01,
        short_funding_rate_percent=0.02,
        funding_rate_difference_percent=0.01,
        next_funding_time=None,
        funding_impact="Good",
        liquidity_status="OK",
        timestamp=timestamp,
    )


if __name__ == "__main__":
    unittest.main()
