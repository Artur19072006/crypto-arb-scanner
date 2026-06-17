import unittest

from app.connectors.okx import OKXPublicConnector


class MockOKXPublicConnector(OKXPublicConnector):
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
            key_value = params.get("instId") or params.get("instType")
        return self.responses[(path, key_value)]


class OKXPublicConnectorTests(unittest.IsolatedAsyncioTestCase):
    async def test_fetch_symbols_filters_usdt_live_swaps(self) -> None:
        connector = MockOKXPublicConnector({
            ("/api/v5/public/instruments", "SWAP"): _instruments_response(),
        })

        symbols = await connector.fetch_symbols()

        self.assertEqual(symbols, ["BTCUSDT", "ETHUSDT"])

    async def test_fetch_symbol_markets_maps_okx_volume(self) -> None:
        connector = MockOKXPublicConnector({
            ("/api/v5/public/instruments", "SWAP"): _instruments_response(),
            ("/api/v5/market/tickers", "SWAP"): _tickers_response(),
        })

        markets = await connector.fetch_symbol_markets()

        self.assertEqual(
            [(market.symbol, market.volume_24h_usd) for market in markets],
            [("BTCUSDT", 650_000_000.0), ("ETHUSDT", 70_000_000.0)],
        )

    async def test_fetch_snapshots_maps_public_tickers_and_funding(self) -> None:
        connector = MockOKXPublicConnector({
            ("/api/v5/public/instruments", "SWAP"): _instruments_response(),
            ("/api/v5/market/tickers", "SWAP"): _tickers_response(),
            ("/api/v5/public/funding-rate", "BTC-USDT-SWAP"): _btc_funding_response(),
            ("/api/v5/public/funding-rate", "ETH-USDT-SWAP"): _empty_funding_response(),
        })

        snapshots = await connector.fetch_snapshots()

        btc = snapshots[0]
        eth = snapshots[1]
        self.assertEqual(len(snapshots), 2)
        self.assertEqual(btc.exchange, "OKX")
        self.assertEqual(btc.symbol, "BTCUSDT")
        self.assertEqual(btc.best_bid, 64999.50)
        self.assertEqual(btc.best_ask, 65000.50)
        self.assertEqual(btc.best_bid_size, 12.0)
        self.assertEqual(btc.best_ask_size, 10.0)
        self.assertEqual(btc.volume_24h_usd, 650_000_000.0)
        self.assertEqual(btc.funding_rate_percent, 0.01)
        self.assertIsNotNone(btc.next_funding_time)
        self.assertEqual(eth.funding_rate_percent, 0)
        self.assertIsNone(eth.next_funding_time)

    async def test_fetch_order_book_maps_public_books_response(self) -> None:
        connector = MockOKXPublicConnector({
            ("/api/v5/market/books", "BTC-USDT-SWAP"): {
                "code": "0",
                "msg": "",
                "data": [
                    {
                        "bids": [["65000.00", "50"], ["64999.00", "125"]],
                        "asks": [["65001.00", "40"], ["65002.00", "110"]],
                        "ts": "1710000000000",
                    }
                ],
            },
            ("/api/v5/public/instruments", "BTC-USDT-SWAP"): {
                "code": "0",
                "msg": "",
                "data": [
                    {
                        "instType": "SWAP",
                        "instId": "BTC-USDT-SWAP",
                        "settleCcy": "USDT",
                        "state": "live",
                        "ctVal": "0.01",
                    }
                ],
            },
        })

        order_book = await connector.fetch_order_book("BTCUSDT", limit=50)

        self.assertEqual(order_book.exchange, "OKX")
        self.assertEqual(order_book.symbol, "BTCUSDT")
        self.assertEqual(order_book.bids[0].price, 65000.00)
        self.assertEqual(order_book.bids[0].quantity, 0.50)
        self.assertEqual(order_book.asks[1].price, 65002.00)
        self.assertEqual(order_book.asks[1].quantity, 1.10)
        self.assertIsNotNone(order_book.timestamp)


def _instruments_response() -> dict:
    return {
        "code": "0",
        "msg": "",
        "data": [
            {
                "instType": "SWAP",
                "instId": "BTC-USDT-SWAP",
                "settleCcy": "USDT",
                "state": "live",
            },
            {
                "instType": "SWAP",
                "instId": "ETH-USDT-SWAP",
                "settleCcy": "USDT",
                "state": "live",
            },
            {
                "instType": "SWAP",
                "instId": "BTC-USD-SWAP",
                "settleCcy": "USD",
                "state": "live",
            },
            {
                "instType": "SWAP",
                "instId": "OLD-USDT-SWAP",
                "settleCcy": "USDT",
                "state": "suspend",
            },
        ],
    }


def _tickers_response() -> dict:
    return {
        "code": "0",
        "msg": "",
        "data": [
            {
                "instId": "BTC-USDT-SWAP",
                "bidPx": "64999.50",
                "bidSz": "12",
                "askPx": "65000.50",
                "askSz": "10",
                "last": "65000",
                "volCcy24h": "10000",
                "ts": "1710000000000",
            },
            {
                "instId": "ETH-USDT-SWAP",
                "bidPx": "3499.00",
                "bidSz": "80",
                "askPx": "3500.00",
                "askSz": "75",
                "last": "3500",
                "volCcy24h": "20000",
                "ts": "1710000001000",
            },
        ],
    }


def _btc_funding_response() -> dict:
    return {
        "code": "0",
        "msg": "",
        "data": [
            {
                "instId": "BTC-USDT-SWAP",
                "fundingRate": "0.00010000",
                "nextFundingTime": "1710003600000",
            }
        ],
    }


def _empty_funding_response() -> dict:
    return {
        "code": "0",
        "msg": "",
        "data": [],
    }


if __name__ == "__main__":
    unittest.main()
