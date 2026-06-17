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
    [tuple[str, ...], int, int],
    list[PublicWebSocketConnector],
]


@dataclass(frozen=True)
class WebSocketRuntimeStatus:
    active_exchanges: tuple[str, ...]
    connected: dict[str, bool]
    connection_count: dict[str, int]
    chunk_count: dict[str, int]
    symbol_count: dict[str, int]
    last_message_at: dict[str, datetime | None]
    last_error_by_exchange: dict[str, str | None]
    reconnect_count: dict[str, int]
    last_update_at: datetime | None


@dataclass
class _ChunkRuntimeState:
    exchange: str
    symbols: tuple[str, ...]
    chunk_index: int
    connected: bool = False
    last_error: str | None = None
    last_message_at: datetime | None = None
    reconnect_count: int = 0


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
        self._chunk_states: dict[str, _ChunkRuntimeState] = {}
        self._signature: tuple[
            tuple[tuple[str, tuple[tuple[str, ...], ...]], ...],
            int,
            int,
            float,
            int,
        ] | None = None
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
        chunked_symbols = _chunked_symbols_by_exchange(
            desired_symbols,
            websocket_config.max_symbols_per_connection,
        )
        signature = (
            tuple(sorted(chunked_symbols.items())),
            websocket_config.reconnect_seconds,
            websocket_config.max_symbols_per_connection,
            websocket_config.connection_start_delay_seconds,
            websocket_config.max_reconnect_attempts,
        )

        async with self._lock:
            if self._signature == signature and self._tasks:
                return

        await self.stop()
        if not chunked_symbols:
            return

        connectors = self._connector_factory(
            tuple(sorted(chunked_symbols)),
            websocket_config.reconnect_seconds,
            websocket_config.max_reconnect_attempts,
        )
        connector_by_name = {
            connector.name: connector
            for connector in connectors
        }
        stop_event = asyncio.Event()
        states: dict[str, _ChunkRuntimeState] = {}
        tasks: dict[str, asyncio.Task[None]] = {}
        task_index = 0
        for exchange, chunks in chunked_symbols.items():
            connector = connector_by_name.get(exchange)
            for chunk_index, symbols in enumerate(chunks, start=1):
                chunk_key = _chunk_key(exchange, chunk_index)
                states[chunk_key] = _ChunkRuntimeState(
                    exchange=exchange,
                    symbols=symbols,
                    chunk_index=chunk_index,
                    last_error=(
                        None
                        if connector is not None
                        else "No WebSocket connector available"
                    ),
                )
                if connector is None:
                    continue

                start_delay_seconds = (
                    websocket_config.connection_start_delay_seconds
                    * task_index
                )
                tasks[chunk_key] = asyncio.create_task(
                    self._run_connector_chunk(
                        connector=connector,
                        chunk_key=chunk_key,
                        symbols=symbols,
                        stop_event=stop_event,
                        start_delay_seconds=start_delay_seconds,
                    )
                )
                task_index += 1

        async with self._lock:
            self._stop_event = stop_event
            self._chunk_states = states
            self._tasks = tasks
            self._signature = signature

    async def stop(self) -> None:
        async with self._lock:
            stop_event = self._stop_event
            tasks = list(self._tasks.values())
            self._stop_event = None
            self._tasks = {}
            self._signature = None
            self._chunk_states = {}

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
            states = list(self._chunk_states.values())
            active_exchanges = tuple(
                sorted({state.exchange for state in states})
            )
            chunk_count = {
                exchange: sum(
                    1 for state in states if state.exchange == exchange
                )
                for exchange in active_exchanges
            }
            connection_count = {
                exchange: sum(
                    1
                    for state in states
                    if state.exchange == exchange and state.connected
                )
                for exchange in active_exchanges
            }
            symbol_count = {
                exchange: sum(
                    len(state.symbols)
                    for state in states
                    if state.exchange == exchange
                )
                for exchange in active_exchanges
            }
            connected = {
                exchange: (
                    chunk_count[exchange] > 0
                    and connection_count[exchange] == chunk_count[exchange]
                )
                for exchange in active_exchanges
            }
            last_message_at = {
                exchange: _latest_datetime(
                    state.last_message_at
                    for state in states
                    if state.exchange == exchange
                )
                for exchange in active_exchanges
            }
            last_error_by_exchange = {
                exchange: _last_error(
                    state.last_error
                    for state in states
                    if state.exchange == exchange
                )
                for exchange in active_exchanges
            }
            reconnect_count = {
                exchange: sum(
                    state.reconnect_count
                    for state in states
                    if state.exchange == exchange
                )
                for exchange in active_exchanges
            }
            update_times = [
                state.last_message_at
                for state in states
                if state.last_message_at is not None
            ]

        return WebSocketRuntimeStatus(
            active_exchanges=active_exchanges,
            connected=connected,
            connection_count=connection_count,
            chunk_count=chunk_count,
            symbol_count=symbol_count,
            last_message_at=last_message_at,
            last_error_by_exchange=last_error_by_exchange,
            reconnect_count=reconnect_count,
            last_update_at=max(update_times) if update_times else None,
        )

    async def _run_connector_chunk(
        self,
        connector: PublicWebSocketConnector,
        chunk_key: str,
        symbols: tuple[str, ...],
        stop_event: asyncio.Event,
        start_delay_seconds: float,
    ) -> None:
        if start_delay_seconds > 0:
            await _sleep_until_stop(stop_event, start_delay_seconds)
        if stop_event.is_set():
            return

        async def handle_snapshot(snapshot: MarketSnapshot) -> None:
            await self._handle_snapshot(chunk_key, snapshot)

        async def handle_connection_status(
            exchange: str,
            connected: bool,
            last_error: str | None,
        ) -> None:
            await self._handle_connection_status(
                chunk_key=chunk_key,
                exchange=exchange,
                connected=connected,
                last_error=last_error,
            )

        reconnect_attempts = 0
        while not stop_event.is_set():
            try:
                await connector.listen(
                    symbols,
                    handle_snapshot,
                    handle_connection_status,
                    stop_event,
                )
                return
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                reconnect_attempts += 1
                await self._handle_connection_status(
                    chunk_key=chunk_key,
                    exchange=connector.name,
                    connected=False,
                    last_error=str(exc),
                )
                if not connector.can_reconnect(reconnect_attempts):
                    return
                await _sleep_until_stop(stop_event, connector.reconnect_seconds)

    async def _handle_snapshot(
        self,
        chunk_key: str,
        snapshot: MarketSnapshot,
    ) -> None:
        await self._cache.update_snapshots([snapshot], source="websocket")
        async with self._lock:
            state = self._chunk_states.setdefault(
                chunk_key,
                _ChunkRuntimeState(
                    exchange=_connector_name_from_exchange(snapshot.exchange),
                    symbols=(snapshot.symbol,),
                    chunk_index=1,
                ),
            )
            state.last_message_at = snapshot.timestamp
            state.last_error = None

    async def _handle_connection_status(
        self,
        chunk_key: str,
        exchange: str,
        connected: bool,
        last_error: str | None,
    ) -> None:
        async with self._lock:
            state = self._chunk_states.setdefault(
                chunk_key,
                _ChunkRuntimeState(
                    exchange=exchange,
                    symbols=(),
                    chunk_index=1,
                ),
            )
            state.connected = connected
            if connected:
                state.last_error = None
            elif last_error:
                state.last_error = last_error
                state.reconnect_count += 1


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
        if connector_name in {"binance", "bybit", "okx", "bitget", "gate"}
        and connector_name in enabled
        and symbols
    }


def _chunked_symbols_by_exchange(
    symbols_by_connector: dict[str, tuple[str, ...]],
    max_symbols_per_connection: int,
) -> dict[str, tuple[tuple[str, ...], ...]]:
    return {
        exchange: tuple(_chunk_symbols(symbols, max_symbols_per_connection))
        for exchange, symbols in symbols_by_connector.items()
        if symbols
    }


def _chunk_symbols(
    symbols: tuple[str, ...],
    max_symbols_per_connection: int,
) -> tuple[tuple[str, ...], ...]:
    chunk_size = max(1, max_symbols_per_connection)
    unique_symbols = tuple(dict.fromkeys(symbols))
    return tuple(
        unique_symbols[index:index + chunk_size]
        for index in range(0, len(unique_symbols), chunk_size)
    )


def _chunk_key(exchange: str, chunk_index: int) -> str:
    return f"{exchange}:{chunk_index}"


def _connector_name_from_exchange(exchange: str) -> str:
    normalized = exchange.lower().strip()
    if normalized == "binance":
        return "binance"
    if normalized == "bybit":
        return "bybit"
    if normalized == "okx":
        return "okx"
    if normalized == "bitget":
        return "bitget"
    return normalized or "unknown"


def _latest_datetime(values) -> datetime | None:
    present_values = [value for value in values if value is not None]
    if not present_values:
        return None
    return max(present_values)


def _last_error(values) -> str | None:
    for value in values:
        if value:
            return value
    return None


async def _sleep_until_stop(stop_event: asyncio.Event, seconds: float) -> None:
    try:
        await asyncio.wait_for(stop_event.wait(), timeout=seconds)
    except TimeoutError:
        return
