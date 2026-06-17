import asyncio
from dataclasses import dataclass
from datetime import datetime
from typing import Callable

from app.connectors.websocket import (
    PublicWebSocketConnector,
    build_public_websocket_connectors,
)
from app.domain.models import AppConfig, MarketSnapshot
from app.services.market_data_cache import MarketDataCache


WebSocketConnectorFactory = Callable[
    [tuple[str, ...], int],
    list[PublicWebSocketConnector],
]


@dataclass(frozen=True)
class WebSocketRuntimeStatus:
    active_exchanges: tuple[str, ...]
    connected: dict[str, bool]
    last_error_by_exchange: dict[str, str | None]
    last_update_at: datetime | None


@dataclass
class _ExchangeRuntimeState:
    connected: bool = False
    last_error: str | None = None
    last_update_at: datetime | None = None
    symbol_count: int = 0


class WebSocketMarketDataManager:
    def __init__(
        self,
        cache: MarketDataCache,
        connector_factory: WebSocketConnectorFactory = build_public_websocket_connectors,
    ) -> None:
        self._cache = cache
        self._connector_factory = connector_factory
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._stop_event: asyncio.Event | None = None
        self._states: dict[str, _ExchangeRuntimeState] = {}
        self._signature: tuple[tuple[str, tuple[str, ...]], int] | None = None
        self._lock = asyncio.Lock()

    async def ensure_started(
        self,
        config: AppConfig,
        symbols_by_connector: dict[str, tuple[str, ...]],
    ) -> None:
        if not _websocket_market_data_enabled(config):
            await self.stop()
            return

        websocket_config = config.market_data.websocket
        desired_symbols = _desired_symbols(
            enabled_exchanges=websocket_config.exchanges,
            symbols_by_connector=symbols_by_connector,
        )
        signature = (
            tuple(sorted(desired_symbols.items())),
            websocket_config.reconnect_seconds,
        )

        async with self._lock:
            if self._signature == signature and self._tasks:
                return

        await self.stop()
        if not desired_symbols:
            return

        connectors = self._connector_factory(
            tuple(sorted(desired_symbols)),
            websocket_config.reconnect_seconds,
        )
        stop_event = asyncio.Event()
        states = {
            connector.name: _ExchangeRuntimeState(
                connected=False,
                symbol_count=len(desired_symbols.get(connector.name, ())),
            )
            for connector in connectors
        }
        tasks = {
            connector.name: asyncio.create_task(
                connector.listen(
                    desired_symbols.get(connector.name, ()),
                    self._handle_snapshot,
                    self._handle_connection_status,
                    stop_event,
                )
            )
            for connector in connectors
            if desired_symbols.get(connector.name)
        }

        async with self._lock:
            self._stop_event = stop_event
            self._states = states
            self._tasks = tasks
            self._signature = signature

    async def stop(self) -> None:
        async with self._lock:
            stop_event = self._stop_event
            tasks = list(self._tasks.values())
            self._stop_event = None
            self._tasks = {}
            self._signature = None
            self._states = {}

        if stop_event is not None:
            stop_event.set()
        for task in tasks:
            task.cancel()
        for task in tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass

    async def status(self) -> WebSocketRuntimeStatus:
        async with self._lock:
            active_exchanges = tuple(sorted(self._states))
            connected = {
                exchange: state.connected
                for exchange, state in self._states.items()
            }
            last_error_by_exchange = {
                exchange: state.last_error
                for exchange, state in self._states.items()
            }
            update_times = [
                state.last_update_at
                for state in self._states.values()
                if state.last_update_at is not None
            ]

        return WebSocketRuntimeStatus(
            active_exchanges=active_exchanges,
            connected=connected,
            last_error_by_exchange=last_error_by_exchange,
            last_update_at=max(update_times) if update_times else None,
        )

    async def _handle_snapshot(self, snapshot: MarketSnapshot) -> None:
        await self._cache.update_snapshots([snapshot], source="websocket")
        async with self._lock:
            state = self._states.setdefault(
                _connector_name_from_exchange(snapshot.exchange),
                _ExchangeRuntimeState(),
            )
            state.last_update_at = snapshot.timestamp
            state.last_error = None

    async def _handle_connection_status(
        self,
        exchange: str,
        connected: bool,
        last_error: str | None,
    ) -> None:
        async with self._lock:
            state = self._states.setdefault(exchange, _ExchangeRuntimeState())
            state.connected = connected
            state.last_error = last_error


def _websocket_market_data_enabled(config: AppConfig) -> bool:
    return (
        config.data_source_mode == "live"
        and config.market_data.mode == "websocket"
        and config.market_data.websocket.enabled
    )


def _desired_symbols(
    enabled_exchanges: tuple[str, ...],
    symbols_by_connector: dict[str, tuple[str, ...]],
) -> dict[str, tuple[str, ...]]:
    enabled = set(enabled_exchanges)
    return {
        connector_name: tuple(dict.fromkeys(symbols))
        for connector_name, symbols in symbols_by_connector.items()
        if connector_name in {"binance", "bybit", "okx"}
        and connector_name in enabled
        and symbols
    }


def _connector_name_from_exchange(exchange: str) -> str:
    normalized = exchange.lower().strip()
    if normalized == "binance":
        return "binance"
    if normalized == "bybit":
        return "bybit"
    if normalized == "okx":
        return "okx"
    return normalized or "unknown"
