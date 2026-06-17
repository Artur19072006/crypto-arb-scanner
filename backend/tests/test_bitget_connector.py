import unittest

from app.connectors.bitget import BitgetPublicConnector


class MockBitgetPublicConnector(BitgetPublicConnector):
    def __init__(self, responses: dict[tuple[str, str | None], dict | list]) -> None:
        super().__init__(
            symbol_allowlist=("BTCUSDT", "ETHUSDT"),
            max_symbols=2,
            base_url="https://example.invalid",
        )
        self.responses = responses

    async def _get_json(
        self,
        path: str,
        params: dict[str, str] | None = None,
    ) -> dict | list:
        key_value = None
        if params:
            key_value = params.get("symbol") or params.get("productType")
        return self.responses[(path, key_value)]


class BitgetPublicConnectorTests(unittest.IsolatedAsyncioTestCase):
    async def test_fetch_symbols_filters_usdt_perpetual_normal_contracts(self) -> None:
        connector = MockBitgetPublicConnector({
            ("/api/v2/mix/market/contracts", "USDT-FUTURES"): _contracts_response(),
        })

        symbols = await connector.fetch_symbols()

        self.assertEqual(symbols, ["BTCUSDT", "ETHUSDT"])

    async def test_fetch_symbol_markets_maps_bitget_volume(self) -> None:
        connector = MockBitgetPublicConnector({
            ("/api/v2/mix/market/contracts", "USDT-FUTURES"): _contracts_response(),
            ("/api/v2/mix/market/tickers", "USDT-FUTURES"): _tickers_response(),
        })

        markets = await connector.fetch_symbol_markets()

        self.assertEqual(
            [(market.symbol, market.volume_24h_usd) for market in markets],
            [("BTCUSDT", 650_000_000.0), ("ETHUSDT", 70_000_000.0)],
        )

    async def test_fetch_snapshots_maps_public_tickers_and_funding(self) -> None:
        connector = MockBitgetPublicConnector({
            ("/api/v2/mix/market/contracts", "USDT-FUTURES"): _contracts_response(),
            ("/api/v2/mix/market/tickers", "USDT-FUTURES"): _tickers_response(),
            (
                "/api/v2/mix/market/current-fund-rate",
                "USDT-FUTURES",
            ): _funding_response(),
        })

        snapshots = await connector.fetch_snapshots()

        btc = snapshots[0]
        eth = snapshots[1]
        self.assertEqual(len(snapshots), 2)
        self.assertEqual(btc.exchange, "Bitget")
        self.assertEqual(btc.symbol, "BTCUSDT")
        self.assertEqual(btc.best_bid, 64999.50)
        self.assertEqual(btc.best_ask, 65000.50)
        self.assertEqual(btc.best_bid_size, 12.0)
        self.assertEqual(btc.best_ask_size, 10.0)
        self.assertEqual(btc.volume_24h_usd, 650_000_000.0)
        self.assertEqual(btc.funding_rate_percent, 0.01)
        self.assertIsNotNone(btc.next_funding_time)
        self.assertEqual(eth.funding_rate_percent, -0.005)
        self.assertIsNotNone(eth.next_funding_time)

    async def test_fetch_order_book_maps_public_merge_depth_response(self) -> None:
        connector = MockBitgetPublicConnector({
            ("/api/v2/mix/market/merge-depth", "BTCUSDT"): {
                "code": "00000",
                "msg": "success",
                "requestTime": 1710000000000,
                "data": {
                    "bids": [["65000.00", "0.50"], ["64999.00", "1.25"]],
                    "asks": [["65001.00", "0.40"], ["65002.00", "1.10"]],
                    "ts": "1710000000000",
                },
            },
        })

        order_book = await connector.fetch_order_book("BTCUSDT", limit=50)

        self.assertEqual(order_book.exchange, "Bitget")
        self.assertEqual(order_book.symbol, "BTCUSDT")
        self.assertEqual(order_book.bids[0].price, 65000.00)
        self.assertEqual(order_book.bids[0].quantity, 0.50)
        self.assertEqual(order_book.asks[1].price, 65002.00)
        self.assertEqual(order_book.asks[1].quantity, 1.10)
        self.assertIsNotNone(order_book.timestamp)


def _contracts_response() -> dict:
    return {
        "code": "00000",
        "msg": "success",
        "data": [
            {
                "symbol": "BTCUSDT",
                "baseCoin": "BTC",
                "quoteCoin": "USDT",
                "symbolType": "perpetual",
                "symbolStatus": "normal",
            },
            {
                "symbol": "ETHUSDT",
                "baseCoin": "ETH",
                "quoteCoin": "USDT",
                "symbolType": "perpetual",
                "symbolStatus": "normal",
            },
            {
                "symbol": "BTCUSDC",
                "baseCoin": "BTC",
                "quoteCoin": "USDC",
                "symbolType": "perpetual",
                "symbolStatus": "normal",
            },
            {
                "symbol": "OLDUSDT",
                "baseCoin": "OLD",
                "quoteCoin": "USDT",
                "symbolType": "perpetual",
                "symbolStatus": "maintain",
            },
            {
                "symbol": "ETHUSDT_260327",
                "baseCoin": "ETH",
                "quoteCoin": "USDT",
                "symbolType": "delivery",
                "symbolStatus": "normal",
            },
        ],
    }


def _tickers_response() -> dict:
    return {
        "code": "00000",
        "msg": "success",
        "data": [
            {
                "symbol": "BTCUSDT",
                "bidPr": "64999.50",
                "askPr": "65000.50",
                "bidSz": "12",
                "askSz": "10",
                "lastPr": "65000",
                "quoteVolume": "640000000",
                "usdtVolume": "650000000",
                "fundingRate": "0.00008",
                "ts": "1710000000000",
            },
            {
                "symbol": "ETHUSDT",
                "bidPr": "3499.00",
                "askPr": "3500.00",
                "bidSz": "80",
                "askSz": "75",
                "lastPr": "3500",
                "quoteVolume": "70000000",
                "usdtVolume": "0",
                "fundingRate": "-0.00005",
                "ts": "1710000001000",
            },
        ],
    }


def _funding_response() -> dict:
    return {
        "code": "00000",
        "msg": "success",
        "data": [
            {
                "symbol": "BTCUSDT",
                "fundingRate": "0.00010000",
                "nextUpdate": "1710003600000",
            },
            {
                "symbol": "ETHUSDT",
                "fundingRate": "-0.00005000",
                "nextUpdate": "1710003600000",
            },
        ],
    }


if __name__ == "__main__":
    unittest.main()
