import unittest

from app.connectors.binance import BinancePublicConnector


class MockBinancePublicConnector(BinancePublicConnector):
    def __init__(self, responses: dict[tuple[str, str | None], dict | list]) -> None:
        super().__init__(
            symbol_allowlist=("BTCUSDT", "ETHUSDT"),
            max_symbols=2,
            base_url="https://example.invalid",
        )
        self.responses = responses

    async def _get_json(self, path: str, params: dict[str, str] | None = None) -> dict | list:
        symbol = params.get("symbol") if params else None
        return self.responses[(path, symbol)]


class BinancePublicConnectorTests(unittest.IsolatedAsyncioTestCase):
    async def test_fetch_symbols_filters_usdt_perpetual_trading_symbols(self) -> None:
        connector = MockBinancePublicConnector({
            ("/fapi/v1/exchangeInfo", None): _exchange_info_response(),
        })

        symbols = await connector.fetch_symbols()

        self.assertEqual(symbols, ["BTCUSDT", "ETHUSDT"])

    async def test_fetch_symbol_markets_maps_usdt_perpetual_volume(self) -> None:
        connector = MockBinancePublicConnector({
            ("/fapi/v1/exchangeInfo", None): _exchange_info_response(),
            ("/fapi/v1/ticker/24hr", None): [
                {"symbol": "BTCUSDT", "quoteVolume": "1000000.50"},
                {"symbol": "ETHUSDT", "quoteVolume": "2000000.25"},
                {"symbol": "XRPUSDT", "quoteVolume": "3000000.00"},
            ],
        })

        markets = await connector.fetch_symbol_markets()

        self.assertEqual(
            [(market.symbol, market.volume_24h_usd) for market in markets],
            [
                ("BTCUSDT", 1_000_000.50),
                ("ETHUSDT", 2_000_000.25),
                ("BTCDOMUSDT", 0.0),
            ],
        )

    async def test_fetch_snapshots_maps_public_responses_to_market_snapshots(self) -> None:
        connector = MockBinancePublicConnector({
            ("/fapi/v1/exchangeInfo", None): _exchange_info_response(),
            ("/fapi/v1/ticker/bookTicker", "BTCUSDT"): {
                "symbol": "BTCUSDT",
                "bidPrice": "65000.10",
                "bidQty": "1.25",
                "askPrice": "65001.20",
                "askQty": "0.75",
                "time": 1710000000000,
            },
            ("/fapi/v1/ticker/24hr", "BTCUSDT"): {
                "symbol": "BTCUSDT",
                "quoteVolume": "123456789.10",
            },
            ("/fapi/v1/premiumIndex", "BTCUSDT"): {
                "symbol": "BTCUSDT",
                "lastFundingRate": "0.00010000",
                "nextFundingTime": 1710003600000,
            },
            ("/fapi/v1/ticker/bookTicker", "ETHUSDT"): {
                "symbol": "ETHUSDT",
                "bidPrice": "3500.00",
                "bidQty": "10.0",
                "askPrice": "3501.00",
                "askQty": "9.0",
                "time": 1710000001000,
            },
            ("/fapi/v1/ticker/24hr", "ETHUSDT"): {
                "symbol": "ETHUSDT",
                "quoteVolume": "98765432.10",
            },
            ("/fapi/v1/premiumIndex", "ETHUSDT"): {},
        })

        snapshots = await connector.fetch_snapshots()

        btc = snapshots[0]
        eth = snapshots[1]
        self.assertEqual(len(snapshots), 2)
        self.assertEqual(btc.exchange, "Binance")
        self.assertEqual(btc.symbol, "BTCUSDT")
        self.assertEqual(btc.best_bid, 65000.10)
        self.assertEqual(btc.best_ask, 65001.20)
        self.assertEqual(btc.best_bid_size, 1.25)
        self.assertEqual(btc.best_ask_size, 0.75)
        self.assertEqual(btc.volume_24h_usd, 123456789.10)
        self.assertEqual(btc.funding_rate_percent, 0.01)
        self.assertIsNotNone(btc.next_funding_time)
        self.assertEqual(eth.funding_rate_percent, 0)
        self.assertIsNone(eth.next_funding_time)

    async def test_fetch_snapshots_uses_bulk_public_tickers_when_available(self) -> None:
        connector = MockBinancePublicConnector({
            ("/fapi/v1/exchangeInfo", None): _exchange_info_response(),
            ("/fapi/v1/ticker/bookTicker", None): [
                {
                    "symbol": "BTCUSDT",
                    "bidPrice": "65000.10",
                    "bidQty": "1.25",
                    "askPrice": "65001.20",
                    "askQty": "0.75",
                    "time": 1710000000000,
                },
                {
                    "symbol": "ETHUSDT",
                    "bidPrice": "3500.00",
                    "bidQty": "10.0",
                    "askPrice": "3501.00",
                    "askQty": "9.0",
                    "time": 1710000001000,
                },
            ],
            ("/fapi/v1/ticker/24hr", None): [
                {"symbol": "BTCUSDT", "quoteVolume": "123456789.10"},
                {"symbol": "ETHUSDT", "quoteVolume": "98765432.10"},
            ],
            ("/fapi/v1/premiumIndex", None): [
                {
                    "symbol": "BTCUSDT",
                    "lastFundingRate": "0.00010000",
                    "nextFundingTime": 1710003600000,
                },
                {"symbol": "ETHUSDT"},
            ],
        })

        snapshots = await connector.fetch_snapshots()

        self.assertEqual(len(snapshots), 2)
        self.assertEqual([snapshot.symbol for snapshot in snapshots], [
            "BTCUSDT",
            "ETHUSDT",
        ])
        self.assertEqual(snapshots[0].volume_24h_usd, 123456789.10)
        self.assertEqual(snapshots[0].funding_rate_percent, 0.01)


def _exchange_info_response() -> dict:
    return {
        "symbols": [
            {
                "symbol": "BTCUSDT",
                "contractType": "PERPETUAL",
                "status": "TRADING",
                "quoteAsset": "USDT",
            },
            {
                "symbol": "ETHUSDT",
                "contractType": "PERPETUAL",
                "status": "TRADING",
                "quoteAsset": "USDT",
            },
            {
                "symbol": "BTCDOMUSDT",
                "contractType": "PERPETUAL",
                "status": "TRADING",
                "quoteAsset": "USDT",
            },
            {
                "symbol": "BTCUSDC",
                "contractType": "PERPETUAL",
                "status": "TRADING",
                "quoteAsset": "USDC",
            },
            {
                "symbol": "OLDUSDT",
                "contractType": "PERPETUAL",
                "status": "BREAK",
                "quoteAsset": "USDT",
            },
        ]
    }


if __name__ == "__main__":
    unittest.main()
