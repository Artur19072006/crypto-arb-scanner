import asyncio
from dataclasses import dataclass

from app.connectors.registry import ConnectorRegistry
from app.domain.models import AppConfig, MarketSymbol, SymbolUniverseSelection
from app.services.symbols import normalize_symbol


@dataclass(frozen=True)
class _SymbolCandidate:
    symbol: str
    volume_24h_usd: float


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
        binance_connector = registry.get("binance")
        bybit_connector = registry.get("bybit")

        if binance_connector is None:
            errors.append("Binance connector is required for auto symbol selection")
        if bybit_connector is None:
            errors.append("Bybit connector is required for auto symbol selection")
        if errors:
            return self._auto_result(config, (), tuple(errors))

        try:
            binance_symbols, bybit_symbols = await asyncio.gather(
                binance_connector.fetch_symbol_markets(),
                bybit_connector.fetch_symbol_markets(),
            )
        except Exception as exc:
            return self._auto_result(
                config,
                (),
                (f"Auto symbol selection failed: {exc}",),
            )

        binance_by_symbol = _market_map(binance_symbols, "Binance")
        bybit_by_symbol = _market_map(bybit_symbols, "Bybit")
        common_symbols = set(binance_by_symbol).intersection(bybit_by_symbol)
        excluded_symbols = set(_normalized_symbols(selection_config.exclude_symbols))
        included_symbols = _normalized_symbols(selection_config.include_symbols)

        candidates_by_symbol: dict[str, _SymbolCandidate] = {}
        for symbol in common_symbols:
            if symbol in excluded_symbols:
                continue

            candidates_by_symbol[symbol] = _SymbolCandidate(
                symbol=symbol,
                volume_24h_usd=min(
                    binance_by_symbol[symbol].volume_24h_usd,
                    bybit_by_symbol[symbol].volume_24h_usd,
                ),
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
        if not selected_symbols:
            errors.append(
                "No common Binance/Bybit symbols matched symbol selection filters"
            )

        return self._auto_result(config, selected_symbols, tuple(errors))

    def _auto_result(
        self,
        config: AppConfig,
        symbols: tuple[str, ...],
        errors: tuple[str, ...] = (),
    ) -> SymbolUniverseSelection:
        return SymbolUniverseSelection(
            mode="auto",
            symbols=symbols,
            min_volume_24h_usd=config.symbol_selection.min_volume_24h_usd,
            max_volume_24h_usd=config.symbol_selection.max_volume_24h_usd,
            errors=errors,
        )


def _market_map(
    markets: list[MarketSymbol],
    exchange: str,
) -> dict[str, MarketSymbol]:
    return {
        normalize_symbol(market.symbol, exchange): market
        for market in markets
        if market.exchange == exchange and normalize_symbol(market.symbol, exchange)
    }


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
