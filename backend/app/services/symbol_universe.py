import asyncio
from dataclasses import dataclass

from app.connectors.registry import ConnectorRegistry
from app.domain.models import AppConfig, MarketSymbol, SymbolUniverseSelection
from app.services.symbols import normalize_symbol


@dataclass(frozen=True)
class _SymbolCandidate:
    symbol: str
    volume_24h_usd: float
    connector_names: tuple[str, ...]
    exchange_count: int


class SymbolUniverseBuilder:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._last_selection = SymbolUniverseSelection()

    async def build(
        self,
        config: AppConfig,
        registry: ConnectorRegistry,
    ) -> SymbolUniverseSelection:
        if config.data_source_mode != "live":
            selection = self._mock_selection(config)
        elif config.symbol_selection.mode == "manual":
            selection = self._manual_selection(config)
        else:
            selection = await self._auto_selection(config, registry)

        async with self._lock:
            self._last_selection = selection

        return selection

    async def get_last_selection(self) -> SymbolUniverseSelection:
        async with self._lock:
            return self._last_selection

    def _mock_selection(self, config: AppConfig) -> SymbolUniverseSelection:
        return SymbolUniverseSelection(
            mode=config.symbol_selection.mode,
            symbols=_limited_normalized_symbols(
                config.symbol_allowlist,
                config.max_symbols,
            ),
            min_volume_24h_usd=config.symbol_selection.min_volume_24h_usd,
            max_volume_24h_usd=config.symbol_selection.max_volume_24h_usd,
        )

    def _manual_selection(self, config: AppConfig) -> SymbolUniverseSelection:
        return SymbolUniverseSelection(
            mode="manual",
            symbols=_limited_normalized_symbols(
                config.symbol_allowlist,
                config.max_symbols,
            ),
            min_volume_24h_usd=config.symbol_selection.min_volume_24h_usd,
            max_volume_24h_usd=config.symbol_selection.max_volume_24h_usd,
        )

    async def _auto_selection(
        self,
        config: AppConfig,
        registry: ConnectorRegistry,
    ) -> SymbolUniverseSelection:
        selection_config = config.symbol_selection
        errors: list[str] = []
        connectors = registry.list_connectors()
        if not connectors:
            return self._auto_result(
                config,
                (),
                {},
                ("No active connectors available for auto symbol selection",),
            )

        connector_results = await asyncio.gather(
            *(connector.fetch_symbol_markets() for connector in connectors),
            return_exceptions=True,
        )
        markets_by_connector: dict[str, list[MarketSymbol]] = {}
        for connector, result in zip(connectors, connector_results):
            if isinstance(result, Exception):
                errors.append(f"{connector.name}: {result}")
                continue
            markets_by_connector[connector.name] = result

        if len(markets_by_connector) < selection_config.min_exchanges_required:
            errors.append(
                "Not enough connector symbol lists for auto symbol selection"
            )
            return self._auto_result(config, (), errors=tuple(errors))

        markets_by_symbol = _markets_by_symbol(markets_by_connector)
        excluded_symbols = set(_normalized_symbols(selection_config.exclude_symbols))
        included_symbols = _normalized_symbols(selection_config.include_symbols)

        candidates_by_symbol: dict[str, _SymbolCandidate] = {}
        for symbol, connector_markets in markets_by_symbol.items():
            if symbol in excluded_symbols:
                continue
            if len(connector_markets) < selection_config.min_exchanges_required:
                continue

            candidates_by_symbol[symbol] = _SymbolCandidate(
                symbol=symbol,
                volume_24h_usd=min(
                    market.volume_24h_usd
                    for market in connector_markets.values()
                ),
                connector_names=tuple(sorted(connector_markets)),
                exchange_count=len(connector_markets),
            )

        included_candidates = [
            candidates_by_symbol[symbol]
            for symbol in included_symbols
            if symbol in candidates_by_symbol
        ]
        volume_filtered_candidates = sorted(
            (
                candidate
                for candidate in candidates_by_symbol.values()
                if _passes_volume_filters(
                    candidate,
                    selection_config.min_volume_24h_usd,
                    selection_config.max_volume_24h_usd,
                )
            ),
            key=lambda candidate: (-candidate.volume_24h_usd, candidate.symbol),
        )

        selected_symbols = _select_symbols(
            included_candidates,
            volume_filtered_candidates,
            selection_config.max_symbols,
        )
        symbols_by_connector = _symbols_by_connector(
            selected_symbols,
            candidates_by_symbol,
            markets_by_connector,
        )
        exchange_count_summary = _exchange_count_summary(
            selected_symbols,
            candidates_by_symbol,
        )
        if not selected_symbols:
            errors.append(
                "No symbols matched auto selection filters on enough exchanges"
            )

        return self._auto_result(
            config,
            selected_symbols,
            symbols_by_connector,
            tuple(errors),
            symbols_on_2_exchanges=exchange_count_summary.get(2, 0),
            symbols_on_3_exchanges=exchange_count_summary.get(3, 0),
        )

    def _auto_result(
        self,
        config: AppConfig,
        symbols: tuple[str, ...],
        symbols_by_connector: dict[str, tuple[str, ...]] | None = None,
        errors: tuple[str, ...] = (),
        symbols_on_2_exchanges: int = 0,
        symbols_on_3_exchanges: int = 0,
    ) -> SymbolUniverseSelection:
        return SymbolUniverseSelection(
            mode="auto",
            symbols=symbols,
            symbols_by_connector=symbols_by_connector or {},
            min_volume_24h_usd=config.symbol_selection.min_volume_24h_usd,
            max_volume_24h_usd=config.symbol_selection.max_volume_24h_usd,
            symbols_on_2_exchanges=symbols_on_2_exchanges,
            symbols_on_3_exchanges=symbols_on_3_exchanges,
            errors=errors,
        )


def _markets_by_symbol(
    markets_by_connector: dict[str, list[MarketSymbol]],
) -> dict[str, dict[str, MarketSymbol]]:
    by_symbol: dict[str, dict[str, MarketSymbol]] = {}
    for connector_name, markets in markets_by_connector.items():
        for market in markets:
            symbol = normalize_symbol(market.symbol, market.exchange)
            if not symbol:
                continue
            by_symbol.setdefault(symbol, {})[connector_name] = market
    return by_symbol


def _symbols_by_connector(
    selected_symbols: tuple[str, ...],
    candidates_by_symbol: dict[str, _SymbolCandidate],
    markets_by_connector: dict[str, list[MarketSymbol]],
) -> dict[str, tuple[str, ...]]:
    selected_by_connector: dict[str, list[str]] = {
        connector_name: []
        for connector_name in markets_by_connector
    }
    for symbol in selected_symbols:
        candidate = candidates_by_symbol[symbol]
        for connector_name in candidate.connector_names:
            selected_by_connector.setdefault(connector_name, []).append(symbol)

    return {
        connector_name: tuple(symbols)
        for connector_name, symbols in selected_by_connector.items()
    }


def _exchange_count_summary(
    selected_symbols: tuple[str, ...],
    candidates_by_symbol: dict[str, _SymbolCandidate],
) -> dict[int, int]:
    summary: dict[int, int] = {}
    for symbol in selected_symbols:
        exchange_count = candidates_by_symbol[symbol].exchange_count
        summary[exchange_count] = summary.get(exchange_count, 0) + 1
    return summary


def _passes_volume_filters(
    candidate: _SymbolCandidate,
    min_volume_24h_usd: float | None,
    max_volume_24h_usd: float | None,
) -> bool:
    if min_volume_24h_usd is not None and candidate.volume_24h_usd < min_volume_24h_usd:
        return False
    if max_volume_24h_usd is not None and candidate.volume_24h_usd > max_volume_24h_usd:
        return False
    return True


def _select_symbols(
    included_candidates: list[_SymbolCandidate],
    volume_filtered_candidates: list[_SymbolCandidate],
    max_symbols: int,
) -> tuple[str, ...]:
    selected: list[str] = []
    for candidate in [*included_candidates, *volume_filtered_candidates]:
        if candidate.symbol in selected:
            continue
        selected.append(candidate.symbol)
        if len(selected) >= max_symbols:
            break

    return tuple(selected)


def _limited_normalized_symbols(
    symbols: tuple[str, ...],
    max_symbols: int,
) -> tuple[str, ...]:
    return _normalized_symbols(symbols)[:max_symbols]


def _normalized_symbols(symbols: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            symbol
            for symbol in (normalize_symbol(raw_symbol) for raw_symbol in symbols)
            if symbol
        )
    )
