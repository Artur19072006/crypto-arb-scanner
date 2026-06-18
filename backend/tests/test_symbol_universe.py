import unittest

from app.connectors.base import ExchangeConnector
from app.connectors.registry import ConnectorRegistry
from app.domain.models import (
    AppConfig,
    ExchangeFees,
    MarketSnapshot,
    MarketSymbol,
    ScannerFilters,
    SymbolSelectionConfig,
    TelegramDisplaySettings,
)
from app.services.symbol_universe import SymbolUniverseBuilder


class StaticSymbolConnector(ExchangeConnector):
    data_source = "test_public_rest"

    def __init__(self, name: str, exchange: str, markets: list[MarketSymbol]) -> None:
        self.name = name
        self.exchange = exchange
        self.markets = markets

    async def fetch_snapshots(
        self,
        symbols: tuple[str, ...] | None = None,
    ) -> list[MarketSnapshot]:
        return []

    async def fetch_symbol_markets(self) -> list[MarketSymbol]:
        return self.markets


class SymbolUniverseBuilderTests(unittest.IsolatedAsyncioTestCase):
    async def test_auto_selects_intersection_between_binance_and_bybit(self) -> None:
        selection = await _build_selection(
            binance_markets=[
                _market("Binance", "BTCUSDT", 1_000_000),
                _market("Binance", "ETHUSDT", 2_000_000),
                _market("Binance", "SOLUSDT", 3_000_000),
            ],
            bybit_markets=[
                _market("Bybit", "ETHUSDT", 2_500_000),
                _market("Bybit", "SOLUSDT", 1_500_000),
                _market("Bybit", "XRPUSDT", 4_000_000),
            ],
            config=_config(min_volume_24h_usd=0),
        )

        self.assertEqual(selection.symbols, ("ETHUSDT", "SOLUSDT"))

    async def test_auto_selects_symbols_on_at_least_two_of_three_connectors(self) -> None:
        selection = await _build_selection(
            binance_markets=[
                _market("Binance", "BTCUSDT", 5_000_000),
                _market("Binance", "SOLUSDT", 1_000_000),
            ],
            bybit_markets=[
                _market("Bybit", "BTCUSDT", 4_000_000),
                _market("Bybit", "ETHUSDT", 3_000_000),
            ],
            okx_markets=[
                _market("OKX", "BTCUSDT", 6_000_000),
                _market("OKX", "ETHUSDT", 2_000_000),
                _market("OKX", "SOLUSDT", 900_000),
                _market("OKX", "DOGEUSDT", 10_000_000),
            ],
            config=_config(min_volume_24h_usd=0),
        )

        self.assertEqual(selection.symbols, ("BTCUSDT", "ETHUSDT", "SOLUSDT"))
        self.assertEqual(selection.symbols_on_2_exchanges, 2)
        self.assertEqual(selection.symbols_on_3_exchanges, 1)
        self.assertEqual(selection.symbols_by_connector["binance"], ("BTCUSDT", "SOLUSDT"))
        self.assertEqual(selection.symbols_by_connector["bybit"], ("BTCUSDT", "ETHUSDT"))
        self.assertEqual(selection.symbols_by_connector["okx"], ("BTCUSDT", "ETHUSDT", "SOLUSDT"))

    async def test_auto_selection_does_not_force_symbols_to_exist_on_binance(self) -> None:
        selection = await _build_selection(
            binance_markets=[],
            bybit_markets=[
                _market("Bybit", "XRPUSDT", 4_000_000),
                _market("Bybit", "DOGEUSDT", 3_000_000),
            ],
            okx_markets=[
                _market("OKX", "DOGEUSDT", 3_500_000),
            ],
            bitget_markets=[
                _market("Bitget", "XRPUSDT", 5_000_000),
            ],
            config=_config(min_volume_24h_usd=0),
        )

        self.assertEqual(selection.symbols, ("XRPUSDT", "DOGEUSDT"))
        self.assertEqual(selection.symbols_by_connector["bybit"], ("XRPUSDT", "DOGEUSDT"))
        self.assertEqual(selection.symbols_by_connector["bitget"], ("XRPUSDT",))
        self.assertEqual(selection.symbols_by_connector["okx"], ("DOGEUSDT",))

    async def test_auto_selection_can_include_gate(self) -> None:
        selection = await _build_selection(
            binance_markets=[],
            bybit_markets=[
                _market("Bybit", "LTCUSDT", 3_000_000),
            ],
            gate_markets=[
                _market("Gate", "LTC_USDT", 4_000_000),
            ],
            config=_config(min_volume_24h_usd=0),
        )

        self.assertEqual(selection.symbols, ("LTCUSDT",))
        self.assertEqual(selection.symbols_by_connector["bybit"], ("LTCUSDT",))
        self.assertEqual(selection.symbols_by_connector["gate"], ("LTCUSDT",))

    async def test_auto_selection_can_include_mexc(self) -> None:
        selection = await _build_selection(
            binance_markets=[],
            bybit_markets=[
                _market("Bybit", "LTCUSDT", 3_000_000),
            ],
            mexc_markets=[
                _market("MEXC", "LTC_USDT", 4_000_000),
            ],
            config=_config(min_volume_24h_usd=0),
        )

        self.assertEqual(selection.symbols, ("LTCUSDT",))
        self.assertEqual(selection.symbols_by_connector["bybit"], ("LTCUSDT",))
        self.assertEqual(selection.symbols_by_connector["mexc"], ("LTCUSDT",))

    async def test_auto_applies_min_and_max_volume_filters(self) -> None:
        selection = await _build_selection(
            binance_markets=[
                _market("Binance", "BTCUSDT", 1_000_000),
                _market("Binance", "ETHUSDT", 300_000),
                _market("Binance", "SOLUSDT", 60_000_000),
            ],
            bybit_markets=[
                _market("Bybit", "BTCUSDT", 900_000),
                _market("Bybit", "ETHUSDT", 700_000),
                _market("Bybit", "SOLUSDT", 70_000_000),
            ],
            config=_config(
                min_volume_24h_usd=400_000,
                max_volume_24h_usd=50_000_000,
            ),
        )

        self.assertEqual(selection.symbols, ("BTCUSDT",))

    async def test_auto_applies_max_symbols_limit_by_volume(self) -> None:
        selection = await _build_selection(
            binance_markets=[
                _market("Binance", "AAAUSDT", 1_000_000),
                _market("Binance", "BBBUSDT", 3_000_000),
                _market("Binance", "CCCUSDT", 2_000_000),
            ],
            bybit_markets=[
                _market("Bybit", "AAAUSDT", 1_000_000),
                _market("Bybit", "BBBUSDT", 2_500_000),
                _market("Bybit", "CCCUSDT", 2_000_000),
            ],
            config=_config(min_volume_24h_usd=0, max_symbols=2),
        )

        self.assertEqual(selection.symbols, ("BBBUSDT", "CCCUSDT"))

    async def test_auto_excludes_blacklisted_symbols(self) -> None:
        selection = await _build_selection(
            binance_markets=[
                _market("Binance", "BTCUSDT", 5_000_000),
                _market("Binance", "SOLUSDT", 1_000_000),
            ],
            bybit_markets=[
                _market("Bybit", "BTCUSDT", 5_000_000),
                _market("Bybit", "SOLUSDT", 1_000_000),
            ],
            config=_config(min_volume_24h_usd=0, exclude_symbols=("BTCUSDT",)),
        )

        self.assertEqual(selection.symbols, ("SOLUSDT",))

    async def test_auto_include_symbols_bypass_volume_filters_when_available(self) -> None:
        selection = await _build_selection(
            binance_markets=[
                _market("Binance", "LOWUSDT", 100_000),
                _market("Binance", "BTCUSDT", 5_000_000),
            ],
            bybit_markets=[
                _market("Bybit", "LOWUSDT", 100_000),
                _market("Bybit", "BTCUSDT", 5_000_000),
            ],
            config=_config(
                min_volume_24h_usd=400_000,
                include_symbols=("LOWUSDT",),
            ),
        )

        self.assertEqual(selection.symbols, ("LOWUSDT", "BTCUSDT"))

    async def test_manual_mode_uses_symbol_allowlist(self) -> None:
        builder = SymbolUniverseBuilder()
        selection = await builder.build(
            _config(
                selection_mode="manual",
                allowlist=("BTCUSDT", "ETHUSDT", "SOLUSDT"),
                legacy_max_symbols=2,
                max_symbols=100,
            ),
            ConnectorRegistry(),
        )

        self.assertEqual(selection.mode, "manual")
        self.assertEqual(selection.symbols, ("BTCUSDT", "ETHUSDT"))

    async def test_mock_mode_keeps_allowlist_without_live_connectors(self) -> None:
        builder = SymbolUniverseBuilder()
        selection = await builder.build(
            _config(
                data_source_mode="mock",
                selection_mode="auto",
                allowlist=("BTCUSDT", "ETHUSDT", "SOLUSDT"),
                legacy_max_symbols=3,
            ),
            ConnectorRegistry(),
        )

        self.assertEqual(selection.mode, "auto")
        self.assertEqual(selection.symbols, ("BTCUSDT", "ETHUSDT", "SOLUSDT"))


async def _build_selection(
    binance_markets: list[MarketSymbol],
    bybit_markets: list[MarketSymbol],
    config: AppConfig,
    okx_markets: list[MarketSymbol] | None = None,
    bitget_markets: list[MarketSymbol] | None = None,
    gate_markets: list[MarketSymbol] | None = None,
    mexc_markets: list[MarketSymbol] | None = None,
):
    registry = ConnectorRegistry()
    registry.register(StaticSymbolConnector("binance", "Binance", binance_markets))
    registry.register(StaticSymbolConnector("bybit", "Bybit", bybit_markets))
    if okx_markets is not None:
        registry.register(StaticSymbolConnector("okx", "OKX", okx_markets))
    if bitget_markets is not None:
        registry.register(StaticSymbolConnector("bitget", "Bitget", bitget_markets))
    if gate_markets is not None:
        registry.register(StaticSymbolConnector("gate", "Gate", gate_markets))
    if mexc_markets is not None:
        registry.register(StaticSymbolConnector("mexc", "MEXC", mexc_markets))
    builder = SymbolUniverseBuilder()
    return await builder.build(config, registry)


def _config(
    data_source_mode: str = "live",
    selection_mode: str = "auto",
    min_volume_24h_usd: float | None = 400_000,
    max_volume_24h_usd: float | None = None,
    max_symbols: int = 100,
    min_exchanges_required: int = 2,
    include_symbols: tuple[str, ...] = (),
    exclude_symbols: tuple[str, ...] = (),
    allowlist: tuple[str, ...] = ("BTCUSDT", "ETHUSDT", "SOLUSDT"),
    legacy_max_symbols: int = 10,
) -> AppConfig:
    return AppConfig(
        data_source_mode=data_source_mode,
        enabled_connectors=("binance", "bybit") if data_source_mode == "live" else ("fake",),
        max_symbols=legacy_max_symbols,
        symbol_allowlist=allowlist,
        symbol_selection=SymbolSelectionConfig(
            mode=selection_mode,
            min_volume_24h_usd=min_volume_24h_usd,
            max_volume_24h_usd=max_volume_24h_usd,
            max_symbols=max_symbols,
            min_exchanges_required=min_exchanges_required,
            include_symbols=include_symbols,
            exclude_symbols=exclude_symbols,
        ),
        fees={
            "Binance": ExchangeFees(maker_percent=0.02, taker_percent=0.05),
            "Bybit": ExchangeFees(maker_percent=0.02, taker_percent=0.055),
            "OKX": ExchangeFees(maker_percent=0.02, taker_percent=0.05),
            "Bitget": ExchangeFees(maker_percent=0.02, taker_percent=0.06),
            "Gate": ExchangeFees(maker_percent=0.02, taker_percent=0.05),
            "MEXC": ExchangeFees(maker_percent=0.02, taker_percent=0.06),
        },
        default_filters=ScannerFilters(
            exchanges=("Binance", "Bybit", "OKX", "Bitget", "Gate", "MEXC")
        ),
        supported_exchanges=("Binance", "Bybit", "OKX", "Bitget", "Gate", "MEXC"),
        telegram=TelegramDisplaySettings(),
        config_source="test",
    )


def _market(exchange: str, symbol: str, volume_24h_usd: float) -> MarketSymbol:
    return MarketSymbol(
        exchange=exchange,
        symbol=symbol,
        volume_24h_usd=volume_24h_usd,
    )


if __name__ == "__main__":
    unittest.main()
