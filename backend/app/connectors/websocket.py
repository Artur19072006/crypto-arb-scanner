import asyncio
import json
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any

import websockets

from app.domain.models import MarketSnapshot
from app.services.symbols import normalize_symbol


SnapshotHandler = Callable[[MarketSnapshot], Awaitable[None]]
ConnectionStatusHandler = Callable[[str, bool, str | None], Awaitable[None]]


class PublicWebSocketConnector(ABC):
    name: str
    exchange_name: str
    data_source: str

    def __init__(self, reconnect_seconds: int = 5) -> None:
        self.reconnect_seconds = max(1, reconnect_seconds)

    @abstractmethod
    async def listen(
        self,
        symbols: tuple[str, ...],
        on_snapshot: SnapshotHandler,
        on_connection_status: ConnectionStatusHandler,
        stop_event: asyncio.Event,
    ) -> None:
        """Stream public top-of-book snapshots until stop_event is set."""


class BinanceBookTickerWebSocketConnector(PublicWebSocketConnector):
    name = "binance"
    exchange_name = "Binance"
    data_source = "binance_public_websocket"

    def __init__(
        self,
        reconnect_seconds: int = 5,
        base_url: str = "wss://fstream.binance.com/public/ws",
    ) -> None:
        super().__init__(reconnect_seconds=reconnect_seconds)
        self.base_url = base_url.rstrip("/")

    async def listen(
        self,
        symbols: tuple[str, ...],
        on_snapshot: SnapshotHandler,
        on_connection_status: ConnectionStatusHandler,
        stop_event: asyncio.Event,
    ) -> None:
        selected_symbols = _normalize_symbols(symbols, "Binance")
        if not selected_symbols:
            await on_connection_status(self.name, False, "No Binance WebSocket symbols selected")
            return

        url = self._stream_url(selected_symbols)
        while not stop_event.is_set():
            try:
                async with websockets.connect(url) as websocket:
                    await on_connection_status(self.name, True, None)
                    while not stop_event.is_set():
                        try:
                            message = await asyncio.wait_for(websocket.recv(), timeout=1)
                        except TimeoutError:
                            continue

                        snapshot = parse_binance_book_ticker_message(message)
                        if snapshot is not None:
                            await on_snapshot(snapshot)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                await on_connection_status(self.name, False, str(exc))
                await _sleep_until_stop(stop_event, self.reconnect_seconds)

        await on_connection_status(self.name, False, None)

    def _stream_url(self, symbols: tuple[str, ...]) -> str:
        streams = "/".join(f"{symbol.lower()}@bookTicker" for symbol in symbols)
        return f"{self.base_url}/{streams}"


class BybitTickerWebSocketConnector(PublicWebSocketConnector):
    name = "bybit"
    exchange_name = "Bybit"
    data_source = "bybit_public_websocket"

    def __init__(
        self,
        reconnect_seconds: int = 5,
        base_url: str = "wss://stream.bybit.com/v5/public/linear",
    ) -> None:
        super().__init__(reconnect_seconds=reconnect_seconds)
        self.base_url = base_url
        self._ticker_state_by_symbol: dict[str, dict[str, Any]] = {}

    async def listen(
        self,
        symbols: tuple[str, ...],
        on_snapshot: SnapshotHandler,
        on_connection_status: ConnectionStatusHandler,
        stop_event: asyncio.Event,
    ) -> None:
        selected_symbols = _normalize_symbols(symbols, "Bybit")
        if not selected_symbols:
            await on_connection_status(self.name, False, "No Bybit WebSocket symbols selected")
            return

        topics = [f"tickers.{symbol}" for symbol in selected_symbols]
        subscribe_message = json.dumps({"op": "subscribe", "args": topics})

        while not stop_event.is_set():
            try:
                async with websockets.connect(self.base_url) as websocket:
                    await websocket.send(subscribe_message)
                    await on_connection_status(self.name, True, None)
                    last_ping_at = datetime.now(timezone.utc)
                    while not stop_event.is_set():
                        try:
                            message = await asyncio.wait_for(websocket.recv(), timeout=1)
                        except TimeoutError:
                            now = datetime.now(timezone.utc)
                            if (now - last_ping_at).total_seconds() >= 20:
                                await websocket.send(json.dumps({"op": "ping"}))
                                last_ping_at = now
                            continue

                        snapshot = self.parse_message(message)
                        if snapshot is not None:
                            await on_snapshot(snapshot)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                await on_connection_status(self.name, False, str(exc))
                await _sleep_until_stop(stop_event, self.reconnect_seconds)

        await on_connection_status(self.name, False, None)

    def parse_message(self, message: str | bytes) -> MarketSnapshot | None:
        return parse_bybit_ticker_message(message, self._ticker_state_by_symbol)


class OKXTickerWebSocketConnector(PublicWebSocketConnector):
    name = "okx"
    exchange_name = "OKX"
    data_source = "okx_public_websocket"

    def __init__(
        self,
        reconnect_seconds: int = 5,
        base_url: str = "wss://ws.okx.com:8443/ws/v5/public",
    ) -> None:
        super().__init__(reconnect_seconds=reconnect_seconds)
        self.base_url = base_url

    async def listen(
        self,
        symbols: tuple[str, ...],
        on_snapshot: SnapshotHandler,
        on_connection_status: ConnectionStatusHandler,
        stop_event: asyncio.Event,
    ) -> None:
        subscription_args = self._subscription_args(symbols)
        if not subscription_args:
            await on_connection_status(self.name, False, "No OKX WebSocket symbols selected")
            return

        subscribe_message = json.dumps(
            {
                "op": "subscribe",
                "args": subscription_args,
            }
        )

        while not stop_event.is_set():
            try:
                async with websockets.connect(self.base_url) as websocket:
                    await websocket.send(subscribe_message)
                    await on_connection_status(self.name, True, None)
                    while not stop_event.is_set():
                        try:
                            message = await asyncio.wait_for(websocket.recv(), timeout=1)
                        except TimeoutError:
                            continue

                        snapshot = parse_okx_ticker_message(message)
                        if snapshot is not None:
                            await on_snapshot(snapshot)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                await on_connection_status(self.name, False, str(exc))
                await _sleep_until_stop(stop_event, self.reconnect_seconds)

        await on_connection_status(self.name, False, None)

    def _subscription_args(self, symbols: tuple[str, ...]) -> list[dict[str, str]]:
        return [
            {"channel": "tickers", "instId": inst_id}
            for inst_id in _okx_inst_ids(symbols)
        ]


def parse_binance_book_ticker_message(message: str | bytes) -> MarketSnapshot | None:
    payload = _json_message(message)
    if not isinstance(payload, dict):
        return None

    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    if not isinstance(data, dict):
        return None

    symbol_type = data.get("st")
    if symbol_type not in (None, 1, "1"):
        return None

    symbol = normalize_symbol(str(data.get("s", "")), "Binance")
    if not symbol:
        return None

    try:
        best_bid = float(data["b"])
        best_ask = float(data["a"])
    except (KeyError, TypeError, ValueError):
        return None

    if best_bid <= 0 or best_ask <= 0:
        return None

    return MarketSnapshot(
        exchange="Binance",
        symbol=symbol,
        best_bid=best_bid,
        best_bid_size=_float_or_zero(data.get("B")),
        best_ask=best_ask,
        best_ask_size=_float_or_zero(data.get("A")),
        volume_24h_usd=0,
        funding_rate_percent=0,
        next_funding_time=None,
        timestamp=_datetime_from_millis(data.get("E") or data.get("T"))
        or datetime.now(timezone.utc),
        source="websocket",
    )


def parse_bybit_ticker_message(
    message: str | bytes,
    ticker_state_by_symbol: dict[str, dict[str, Any]] | None = None,
) -> MarketSnapshot | None:
    payload = _json_message(message)
    if not isinstance(payload, dict):
        return None
    if payload.get("op") in {"subscribe", "pong", "ping"}:
        return None

    data = payload.get("data")
    if isinstance(data, list):
        data = data[0] if data else None
    if not isinstance(data, dict):
        return None

    symbol = normalize_symbol(str(data.get("symbol", "")), "Bybit")
    if not symbol:
        topic = str(payload.get("topic", ""))
        symbol = normalize_symbol(topic.removeprefix("tickers."), "Bybit")
    if not symbol:
        return None

    state_by_symbol = ticker_state_by_symbol if ticker_state_by_symbol is not None else {}
    state = dict(state_by_symbol.get(symbol, {}))
    state.update(data)
    state_by_symbol[symbol] = state

    try:
        best_bid = float(state["bid1Price"])
        best_ask = float(state["ask1Price"])
    except (KeyError, TypeError, ValueError):
        return None

    if best_bid <= 0 or best_ask <= 0:
        return None

    return MarketSnapshot(
        exchange="Bybit",
        symbol=symbol,
        best_bid=best_bid,
        best_bid_size=_float_or_zero(state.get("bid1Size")),
        best_ask=best_ask,
        best_ask_size=_float_or_zero(state.get("ask1Size")),
        volume_24h_usd=_float_or_zero(state.get("turnover24h")),
        funding_rate_percent=_float_or_zero(state.get("fundingRate")) * 100,
        next_funding_time=_datetime_from_millis(state.get("nextFundingTime")),
        timestamp=_datetime_from_millis(payload.get("ts")) or datetime.now(timezone.utc),
        source="websocket",
    )


def parse_okx_ticker_message(message: str | bytes) -> MarketSnapshot | None:
    payload = _json_message(message)
    if not isinstance(payload, dict):
        return None
    if payload.get("event") or payload.get("op"):
        return None

    data = payload.get("data")
    if not isinstance(data, list) or not data:
        return None
    ticker = data[0]
    if not isinstance(ticker, dict):
        return None
    if ticker.get("instType") not in (None, "SWAP"):
        return None

    inst_id = str(ticker.get("instId") or "")
    if not inst_id.endswith("-USDT-SWAP"):
        return None

    symbol = normalize_symbol(inst_id, "OKX")
    if not symbol:
        return None

    try:
        best_bid = float(ticker["bidPx"])
        best_ask = float(ticker["askPx"])
    except (KeyError, TypeError, ValueError):
        return None

    if best_bid <= 0 or best_ask <= 0:
        return None

    return MarketSnapshot(
        exchange="OKX",
        symbol=symbol,
        best_bid=best_bid,
        best_bid_size=_float_or_zero(ticker.get("bidSz")),
        best_ask=best_ask,
        best_ask_size=_float_or_zero(ticker.get("askSz")),
        volume_24h_usd=_okx_volume_24h_usd(ticker),
        funding_rate_percent=0,
        next_funding_time=None,
        timestamp=_datetime_from_millis(ticker.get("ts")) or datetime.now(timezone.utc),
        source="websocket",
    )


def build_public_websocket_connectors(
    exchanges: tuple[str, ...],
    reconnect_seconds: int,
) -> list[PublicWebSocketConnector]:
    connectors: list[PublicWebSocketConnector] = []
    enabled = set(exchanges)
    if "binance" in enabled:
        connectors.append(
            BinanceBookTickerWebSocketConnector(
                reconnect_seconds=reconnect_seconds,
            )
        )
    if "bybit" in enabled:
        connectors.append(
            BybitTickerWebSocketConnector(
                reconnect_seconds=reconnect_seconds,
            )
        )
    if "okx" in enabled:
        connectors.append(
            OKXTickerWebSocketConnector(
                reconnect_seconds=reconnect_seconds,
            )
        )
    return connectors


def _json_message(message: str | bytes) -> Any:
    if isinstance(message, bytes):
        message = message.decode("utf-8")
    try:
        return json.loads(message)
    except (TypeError, ValueError):
        return None


def _datetime_from_millis(value: object) -> datetime | None:
    if value in (None, "", 0, "0"):
        return None

    try:
        return datetime.fromtimestamp(int(value) / 1000, tz=timezone.utc)
    except (TypeError, ValueError, OSError):
        return None


def _normalize_symbols(symbols: tuple[str, ...], exchange: str) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            symbol
            for symbol in (normalize_symbol(raw_symbol, exchange) for raw_symbol in symbols)
            if symbol
        )
    )


def _okx_inst_ids(symbols: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            inst_id
            for inst_id in (_okx_inst_id(raw_symbol) for raw_symbol in symbols)
            if inst_id
        )
    )


def _okx_inst_id(symbol: str) -> str:
    normalized = normalize_symbol(symbol, "OKX")
    if not normalized.endswith("USDT") or len(normalized) <= 4:
        return ""
    return f"{normalized[:-4]}-USDT-SWAP"


def _float_or_zero(value: object) -> float:
    if value in (None, ""):
        return 0.0

    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _okx_volume_24h_usd(ticker: dict[str, Any]) -> float:
    last_price = _float_or_zero(ticker.get("last"))
    base_volume = _float_or_zero(ticker.get("volCcy24h"))
    return last_price * base_volume


async def _sleep_until_stop(stop_event: asyncio.Event, seconds: int) -> None:
    try:
        await asyncio.wait_for(stop_event.wait(), timeout=seconds)
    except TimeoutError:
        return
