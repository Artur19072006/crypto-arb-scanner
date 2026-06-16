from app.connectors.base import ExchangeConnector
from app.connectors.binance import BinancePublicConnector
from app.connectors.bybit import BybitPublicConnector
from app.connectors.fake import FakeExchangeConnector
from app.connectors.okx import OKXPublicConnector
from app.domain.models import AppConfig


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


def build_connector_registry(
    data_source_mode: str = "mock",
    enabled_connectors: tuple[str, ...] = (),
    symbol_allowlist: tuple[str, ...] = (),
    max_symbols: int = 10,
) -> ConnectorRegistry:
    registry = ConnectorRegistry()
    enabled = set(enabled_connectors)

    if data_source_mode == "mock":
        registry.register(FakeExchangeConnector())
        return registry

    if data_source_mode == "live" and (not enabled or "binance" in enabled):
        registry.register(
            BinancePublicConnector(
                symbol_allowlist=symbol_allowlist,
                max_symbols=max_symbols,
            )
        )

    if data_source_mode == "live" and (not enabled or "bybit" in enabled):
        registry.register(
            BybitPublicConnector(
                symbol_allowlist=symbol_allowlist,
                max_symbols=max_symbols,
            )
        )

    if data_source_mode == "live" and (not enabled or "okx" in enabled):
        registry.register(
            OKXPublicConnector(
                symbol_allowlist=symbol_allowlist,
                max_symbols=max_symbols,
            )
        )

    # TODO: Register Bitget, Gate, and KuCoin public connectors here later.
    return registry


def build_connector_registry_from_config(config: AppConfig) -> ConnectorRegistry:
    return build_connector_registry(
        data_source_mode=config.data_source_mode,
        enabled_connectors=config.enabled_connectors,
        symbol_allowlist=config.symbol_allowlist,
        max_symbols=config.max_symbols,
    )
