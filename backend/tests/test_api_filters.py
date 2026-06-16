import unittest

from app.api.routes import _build_filters, _parse_exchanges


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


if __name__ == "__main__":
    unittest.main()
