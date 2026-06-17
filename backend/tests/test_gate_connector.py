import unittest
from datetime import datetime, timezone

from app.connectors.gate import GatePublicConnector, _gate_contract


class MockGatePublicConnector(GatePublicConnector):
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
            key_value = params.get("contract")
        return self.responses[(path, key_value)]


class GatePublicConnectorTests(unittest.IsolatedAsyncioTestCase):
    async def test_fetch_symbols_filters_usdt_perpetual_live_contracts(self) -> None:
        connector = MockGatePublicConnector({
            ("/futures/usdt/contracts", None): _contracts_response(),
        })

        symbols = await connector.fetch_symbols()

        self.assertEqual(symbols, ["BTCUSDT", "ETHUSDT"])

    async def test_fetch_symbol_markets_maps_gate_volume(self) -> None:
        connector = MockGatePublicConnector({
            ("/futures/usdt/contracts", None): _contracts_response(),
            ("/futures/usdt/tickers", None): _tickers_response(),
        })

        markets = await connector.fetch_symbol_markets()

        self.assertEqual(
            [(market.symbol, market.volume_24h_usd) for market in markets],
            [("BTCUSDT", 650_000_000.0), ("ETHUSDT", 70_000_000.0)],
        )

    async def test_fetch_snapshots_maps_public_tickers_and_funding_context(self) -> None:
        connector = MockGatePublicConnector({
            ("/futures/usdt/contracts", None): _contracts_response(),
            ("/futures/usdt/tickers", None): _tickers_response(),
        })

        snapshots = await connector.fetch_snapshots()

        btc = snapshots[0]
        eth = snapshots[1]
        self.assertEqual(len(snapshots), 2)
        self.assertEqual(btc.exchange, "Gate")
        self.assertEqual(btc.symbol, "BTCUSDT")
        self.assertEqual(btc.best_bid, 64999.50)
        self.assertEqual(btc.best_ask, 65000.50)
        self.assertEqual(btc.best_bid_size, 0.50)
        self.assertEqual(btc.best_ask_size, 0.40)
        self.assertEqual(btc.volume_24h_usd, 650_000_000.0)
        self.assertEqual(btc.funding_rate_percent, 0.01)
        self.assertEqual(
            btc.next_funding_time,
            datetime.fromtimestamp(1710003600, tz=timezone.utc),
        )
        self.assertEqual(eth.funding_rate_percent, -0.005)
        self.assertIsNotNone(eth.next_funding_time)

    async def test_fetch_snapshots_uses_selected_symbols_only(self) -> None:
        connector = MockGatePublicConnector({
            ("/futures/usdt/contracts", None): _contracts_response(),
            ("/futures/usdt/tickers", None): _tickers_response(),
        })

        snapshots = await connector.fetch_snapshots(("eth_usdt",))

        self.assertEqual([snapshot.symbol for snapshot in snapshots], ["ETHUSDT"])

    def test_maps_internal_symbols_to_gate_contract_format(self) -> None:
        self.assertEqual(_gate_contract("BTCUSDT"), "BTC_USDT")
        self.assertEqual(_gate_contract("eth_usdt"), "ETH_USDT")
        self.assertEqual(_gate_contract("BTCUSDC"), "")


def _contracts_response() -> list[dict]:
    return [
        {
            "name": "BTC_USDT",
            "type": "direct",
            "in_delisting": False,
            "funding_rate": "0.000100",
            "funding_next_apply": 1710003600,
        },
        {
            "name": "ETH_USDT",
            "type": "direct",
            "in_delisting": False,
            "funding_rate": "-0.000050",
            "funding_next_apply": "1710003600",
        },
        {
            "name": "BTC_USD",
            "type": "inverse",
            "in_delisting": False,
        },
        {
            "name": "OLD_USDT",
            "type": "direct",
            "in_delisting": True,
        },
        {
            "name": "ETH_USDT_260327",
            "type": "direct",
            "in_delisting": False,
        },
    ]


def _tickers_response() -> list[dict]:
    return [
        {
            "contract": "BTC_USDT",
            "last": "65000",
            "highest_bid": "64999.50",
            "lowest_ask": "65000.50",
            "highest_bid_size": "0.50",
            "lowest_ask_size": "0.40",
            "volume_24h_quote": "650000000",
            "funding_rate": "0.000100",
        },
        {
            "contract": "ETH_USDT",
            "last": "3500",
            "highest_bid": "3499.00",
            "lowest_ask": "3500.00",
            "volume_24h_quote": "0",
            "volume_24h": "20000",
            "funding_rate": "-0.000050",
        },
    ]


if __name__ == "__main__":
    unittest.main()
