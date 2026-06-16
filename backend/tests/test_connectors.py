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

    async def test_live_mode_is_reserved_and_registers_no_connectors_yet(self) -> None:
        registry = build_connector_registry("live")

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
