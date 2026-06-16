import unittest

from app.connectors.bybit import BybitPublicConnector


class MockBybitPublicConnector(BybitPublicConnector):
    def __init__(self, responses: dict[str, dict | list]) -> None:
        super().__init__(
            symbol_allowlist=("BTCUSDT", "ETHUSDT"),
            max_symbols=2,
            base_url="https://example.invalid",
        )
        self.responses = responses

    async def _get_json(self, path: str, params: dict[str, str] | None = None) -> dict | list:
        return self.responses[path]


class BybitPublicConnectorTests(unittest.IsolatedAsyncioTestCase):
    async def test_fetch_symbols_filters_usdt_linear_perpetual_trading_symbols(self) -> None:
        connector = MockBybitPublicConnector({
            "/v5/market/instruments-info": _instruments_response(),
        })

        symbols = await connector.fetch_symbols()

        self.assertEqual(symbols, ["BTCUSDT", "ETHUSDT"])

    async def test_fetch_symbol_markets_maps_usdt_linear_perpetual_volume(self) -> None:
        connector = MockBybitPublicConnector({
            "/v5/market/instruments-info": _instruments_response(),
            "/v5/market/tickers": _tickers_response(),
        })

        markets = await connector.fetch_symbol_markets()

        self.assertEqual(
            [(market.symbol, market.volume_24h_usd) for market in markets],
            [("BTCUSDT", 123_456_789.10), ("ETHUSDT", 98_765_432.10)],
        )

    async def test_fetch_snapshots_maps_public_responses_to_market_snapshots(self) -> None:
        connector = MockBybitPublicConnector({
            "/v5/market/instruments-info": _instruments_response(),
            "/v5/market/tickers": _tickers_response(),
        })

        snapshots = await connector.fetch_snapshots()

        btc = snapshots[0]
        eth = snapshots[1]
        self.assertEqual(len(snapshots), 2)
        self.assertEqual(btc.exchange, "Bybit")
        self.assertEqual(btc.symbol, "BTCUSDT")
        self.assertEqual(btc.best_bid, 65010.50)
        self.assertEqual(btc.best_ask, 65011.00)
        self.assertEqual(btc.best_bid_size, 1.20)
        self.assertEqual(btc.best_ask_size, 0.80)
        self.assertEqual(btc.volume_24h_usd, 123456789.10)
        self.assertEqual(btc.funding_rate_percent, 0.01)
        self.assertIsNotNone(btc.next_funding_time)
        self.assertEqual(eth.funding_rate_percent, 0)
        self.assertIsNone(eth.next_funding_time)


def _instruments_response() -> dict:
    return {
        "retCode": 0,
        "retMsg": "OK",
        "result": {
            "list": [
                {
                    "symbol": "BTCUSDT",
                    "contractType": "LinearPerpetual",
                    "status": "Trading",
                    "quoteCoin": "USDT",
                },
                {
                    "symbol": "ETHUSDT",
                    "contractType": "LinearPerpetual",
                    "status": "Trading",
                    "quoteCoin": "USDT",
                },
                {
                    "symbol": "BTCUSD",
                    "contractType": "InversePerpetual",
                    "status": "Trading",
                    "quoteCoin": "USD",
                },
                {
                    "symbol": "OLDUSDT",
                    "contractType": "LinearPerpetual",
                    "status": "PreLaunch",
                    "quoteCoin": "USDT",
                },
            ],
            "nextPageCursor": "",
        },
        "time": 1710000000000,
    }


def _tickers_response() -> dict:
    return {
        "retCode": 0,
        "retMsg": "OK",
        "result": {
            "list": [
                {
                    "symbol": "BTCUSDT",
                    "bid1Price": "65010.50",
                    "bid1Size": "1.20",
                    "ask1Price": "65011.00",
                    "ask1Size": "0.80",
                    "turnover24h": "123456789.10",
                    "fundingRate": "0.00010000",
                    "nextFundingTime": "1710003600000",
                },
                {
                    "symbol": "ETHUSDT",
                    "bid1Price": "3500.00",
                    "bid1Size": "10.0",
                    "ask1Price": "3501.00",
                    "ask1Size": "9.0",
                    "turnover24h": "98765432.10",
                    "fundingRate": "",
                    "nextFundingTime": "",
                },
            ],
        },
        "time": 1710000000000,
    }


if __name__ == "__main__":
    unittest.main()
