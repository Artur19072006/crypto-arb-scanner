import unittest
from datetime import datetime, timezone

from app.connectors.mexc import MexcPublicConnector, _mexc_contract


class MockMexcPublicConnector(MexcPublicConnector):
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
            key_value = params.get("symbol") or params.get("limit")
        return self.responses[(path, key_value)]


class MexcPublicConnectorTests(unittest.IsolatedAsyncioTestCase):
    async def test_fetch_symbols_filters_usdt_perpetual_enabled_contracts(self) -> None:
        connector = MockMexcPublicConnector({
            ("/api/v1/contract/detail", None): _contracts_response(),
        })

        symbols = await connector.fetch_symbols()

        self.assertEqual(symbols, ["BTCUSDT", "ETHUSDT"])

    async def test_fetch_symbol_markets_maps_mexc_volume(self) -> None:
        connector = MockMexcPublicConnector({
            ("/api/v1/contract/detail", None): _contracts_response(),
            ("/api/v1/contract/ticker", None): _tickers_response(),
        })

        markets = await connector.fetch_symbol_markets()

        self.assertEqual(
            [(market.symbol, market.volume_24h_usd) for market in markets],
            [("BTCUSDT", 650_000_000.0), ("ETHUSDT", 70_000_000.0)],
        )

    async def test_fetch_snapshots_maps_public_tickers_and_current_funding(self) -> None:
        connector = MockMexcPublicConnector({
            ("/api/v1/contract/detail", None): _contracts_response(),
            ("/api/v1/contract/ticker", None): _tickers_response(),
        })

        snapshots = await connector.fetch_snapshots()

        btc = snapshots[0]
        eth = snapshots[1]
        self.assertEqual(len(snapshots), 2)
        self.assertEqual(btc.exchange, "MEXC")
        self.assertEqual(btc.symbol, "BTCUSDT")
        self.assertEqual(btc.best_bid, 64999.50)
        self.assertEqual(btc.best_ask, 65000.50)
        self.assertEqual(btc.best_bid_size, 0.0)
        self.assertEqual(btc.best_ask_size, 0.0)
        self.assertEqual(btc.volume_24h_usd, 650_000_000.0)
        self.assertEqual(btc.funding_rate_percent, 0.01)
        self.assertIsNone(btc.next_funding_time)
        self.assertEqual(
            btc.timestamp,
            datetime.fromtimestamp(1710000000000 / 1000, tz=timezone.utc),
        )
        self.assertEqual(eth.funding_rate_percent, -0.005)

    async def test_fetch_snapshots_uses_selected_symbols_only(self) -> None:
        connector = MockMexcPublicConnector({
            ("/api/v1/contract/detail", None): _contracts_response(),
            ("/api/v1/contract/ticker", None): _tickers_response(),
        })

        snapshots = await connector.fetch_snapshots(("eth-usdt",))

        self.assertEqual([snapshot.symbol for snapshot in snapshots], ["ETHUSDT"])

    async def test_fetch_order_book_maps_public_depth_contract_volume_to_quantity(self) -> None:
        connector = MockMexcPublicConnector({
            ("/api/v1/contract/detail", "BTC_USDT"): {
                "success": True,
                "code": 0,
                "data": {
                    "symbol": "BTC_USDT",
                    "quoteCoin": "USDT",
                    "settleCoin": "USDT",
                    "contractSize": 0.0001,
                    "state": 0,
                    "isHidden": False,
                },
            },
            ("/api/v1/contract/depth/BTC_USDT", "50"): {
                "bids": [[65000.00, 5000, 2], [64999.00, 2500, 1]],
                "asks": [[65001.00, 4000, 2], [65002.00, 1100, 1]],
                "version": 1,
                "timestamp": 1710000000000,
            },
        })

        order_book = await connector.fetch_order_book("BTCUSDT", limit=50)

        self.assertEqual(order_book.exchange, "MEXC")
        self.assertEqual(order_book.symbol, "BTCUSDT")
        self.assertEqual(order_book.bids[0].price, 65000.00)
        self.assertEqual(order_book.bids[0].quantity, 0.50)
        self.assertEqual(order_book.asks[1].price, 65002.00)
        self.assertEqual(order_book.asks[1].quantity, 0.11)
        self.assertIsNotNone(order_book.timestamp)

    def test_maps_internal_symbols_to_mexc_contract_format(self) -> None:
        self.assertEqual(_mexc_contract("BTCUSDT"), "BTC_USDT")
        self.assertEqual(_mexc_contract("eth_usdt"), "ETH_USDT")
        self.assertEqual(_mexc_contract("SOL-USDT"), "SOL_USDT")
        self.assertEqual(_mexc_contract("BTCUSDC"), "")


def _contracts_response() -> dict:
    return {
        "success": True,
        "code": 0,
        "data": [
            {
                "symbol": "BTC_USDT",
                "quoteCoin": "USDT",
                "settleCoin": "USDT",
                "contractSize": 0.0001,
                "state": 0,
                "isHidden": False,
            },
            {
                "symbol": "ETH-USDT",
                "quoteCoin": "USDT",
                "settleCoin": "USDT",
                "contractSize": 0.001,
                "state": 0,
                "isHidden": False,
            },
            {
                "symbol": "BTC_USD",
                "quoteCoin": "USD",
                "settleCoin": "BTC",
                "contractSize": 1,
                "state": 0,
            },
            {
                "symbol": "OLD_USDT",
                "quoteCoin": "USDT",
                "settleCoin": "USDT",
                "contractSize": 1,
                "state": 3,
            },
            {
                "symbol": "HIDDEN_USDT",
                "quoteCoin": "USDT",
                "settleCoin": "USDT",
                "contractSize": 1,
                "state": 0,
                "isHidden": True,
            },
        ],
    }


def _tickers_response() -> dict:
    return {
        "success": True,
        "code": 0,
        "data": [
            {
                "symbol": "BTC_USDT",
                "lastPrice": 65000,
                "bid1": 64999.50,
                "ask1": 65000.50,
                "volume24": 10_000,
                "amount24": 650_000_000,
                "fundingRate": 0.0001,
                "timestamp": 1710000000000,
            },
            {
                "symbol": "ETH-USDT",
                "lastPrice": 3500,
                "bid1": 3499.00,
                "ask1": 3500.00,
                "volume24": 20_000,
                "amount24": 0,
                "fundingRate": -0.00005,
                "timestamp": 1710000001000,
            },
        ],
    }


if __name__ == "__main__":
    unittest.main()
