from app.connectors.base import ExchangeConnector
from app.connectors.fake import FakeExchangeConnector


class ConnectorRegistry:
    def __init__(self) -> None:
        self._connectors: dict[str, ExchangeConnector] = {}

    def register(self, connector: ExchangeConnector) -> None:
        self._connectors[connector.name] = connector

    def get(self, name: str) -> ExchangeConnector | None:
        return self._connectors.get(name)

    def list_connectors(self) -> list[ExchangeConnector]:
        return [
            self._connectors[name]
            for name in sorted(self._connectors)
        ]

    def list_names(self) -> tuple[str, ...]:
        return tuple(connector.name for connector in self.list_connectors())


def build_connector_registry(data_source_mode: str = "mock") -> ConnectorRegistry:
    registry = ConnectorRegistry()

    if data_source_mode == "mock":
        registry.register(FakeExchangeConnector())

    # TODO: Register BinanceConnector, BybitConnector, and later connectors here
    # when real market-data integrations are implemented.
    return registry
