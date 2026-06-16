import unittest

from app.connectors.fake import FakeExchangeConnector
from app.connectors.registry import ConnectorRegistry, build_connector_registry


class ConnectorRegistryTests(unittest.IsolatedAsyncioTestCase):
    async def test_registers_and_lists_fake_connector_in_mock_mode(self) -> None:
        registry = build_connector_registry("mock")

        self.assertEqual(registry.list_names(), ("fake",))
        connector = registry.get("fake")
        self.assertIsInstance(connector, FakeExchangeConnector)
        self.assertEqual(connector.data_source, "fake_connector")

        snapshots = await connector.fetch_snapshots()

        self.assertGreater(len(snapshots), 0)
        self.assertEqual({snapshot.exchange for snapshot in snapshots}, {
            "Binance",
            "Bybit",
            "OKX",
            "Bitget",
        })

    async def test_mock_mode_uses_fake_even_if_live_connectors_are_configured(self) -> None:
        registry = build_connector_registry(
            data_source_mode="mock",
            enabled_connectors=("binance", "bybit"),
            symbol_allowlist=("BTCUSDT",),
            max_symbols=1,
        )

        self.assertEqual(registry.list_names(), ("fake",))

    async def test_live_mode_registers_binance_public_connector(self) -> None:
        registry = build_connector_registry(
            data_source_mode="live",
            enabled_connectors=("binance",),
            symbol_allowlist=("BTCUSDT",),
            max_symbols=1,
        )

        self.assertEqual(registry.list_names(), ("binance",))
        self.assertEqual(registry.get("binance").data_source, "binance_public_rest")

    async def test_live_mode_registers_binance_and_bybit_public_connectors(self) -> None:
        registry = build_connector_registry(
            data_source_mode="live",
            enabled_connectors=("binance", "bybit"),
            symbol_allowlist=("BTCUSDT",),
            max_symbols=1,
        )

        self.assertEqual(registry.list_names(), ("binance", "bybit"))
        self.assertEqual(registry.get("binance").data_source, "binance_public_rest")
        self.assertEqual(registry.get("bybit").data_source, "bybit_public_rest")

    async def test_live_mode_registers_okx_public_connector(self) -> None:
        registry = build_connector_registry(
            data_source_mode="live",
            enabled_connectors=("okx",),
            symbol_allowlist=("BTCUSDT",),
            max_symbols=1,
        )

        self.assertEqual(registry.list_names(), ("okx",))
        self.assertEqual(registry.get("okx").data_source, "okx_public_rest")

    async def test_live_mode_registers_binance_bybit_and_okx_public_connectors(self) -> None:
        registry = build_connector_registry(
            data_source_mode="live",
            enabled_connectors=("binance", "bybit", "okx"),
            symbol_allowlist=("BTCUSDT",),
            max_symbols=1,
        )

        self.assertEqual(registry.list_names(), ("binance", "bybit", "okx"))
        self.assertEqual(registry.get("binance").data_source, "binance_public_rest")
        self.assertEqual(registry.get("bybit").data_source, "bybit_public_rest")
        self.assertEqual(registry.get("okx").data_source, "okx_public_rest")

    async def test_live_mode_registers_bybit_public_connector(self) -> None:
        registry = build_connector_registry(
            data_source_mode="live",
            enabled_connectors=("bybit",),
            symbol_allowlist=("BTCUSDT",),
            max_symbols=1,
        )

        self.assertEqual(registry.list_names(), ("bybit",))
        self.assertEqual(registry.get("bybit").data_source, "bybit_public_rest")

    async def test_live_mode_with_no_supported_connector_registers_none(self) -> None:
        registry = build_connector_registry(
            data_source_mode="live",
            enabled_connectors=("fake",),
            symbol_allowlist=("BTCUSDT",),
            max_symbols=1,
        )

        self.assertEqual(registry.list_names(), ())

    async def test_manual_registration_replaces_connector_by_name(self) -> None:
        registry = ConnectorRegistry()
        connector = FakeExchangeConnector()

        registry.register(connector)
        registry.register(connector)

        self.assertEqual(registry.get("fake"), connector)
        self.assertEqual(registry.list_names(), ("fake",))


if __name__ == "__main__":
    unittest.main()
