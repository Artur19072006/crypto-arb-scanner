import asyncio
import json
import time
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any

import websockets

from app.domain.models import MarketSnapshot
from app.services.symbols import exchange_name_key, normalize_symbol


SnapshotHandler = Callable[[MarketSnapshot], Awaitable[None]]
ConnectionStatusHandler = Callable[[str, bool, str | None], Awaitable[None]]


class PublicWebSocketConnector(ABC):
    name: str
    exchange_name: str
    data_source: str

    def __init__(
        self,
        reconnect_seconds: int = 5,
        max_reconnect_attempts: int = 0,
    ) -> None:
        self.reconnect_seconds = max(1, reconnect_seconds)
        self.max_reconnect_attempts = max(0, max_reconnect_attempts)

    def can_reconnect(self, reconnect_attempts: int) -> bool:
        return (
            self.max_reconnect_attempts == 0
            or reconnect_attempts < self.max_reconnect_attempts
        )

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
        max_reconnect_attempts: int = 0,
        base_url: str = "wss://fstream.binance.com/public/ws",
    ) -> None:
        super().__init__(
            reconnect_seconds=reconnect_seconds,
            max_reconnect_attempts=max_reconnect_attempts,
        )
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
        reconnect_attempts = 0
        while not stop_event.is_set():
            try:
                async with websockets.connect(url) as websocket:
                    reconnect_attempts = 0
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
                reconnect_attempts += 1
                await on_connection_status(self.name, False, str(exc))
                if not self.can_reconnect(reconnect_attempts):
                    break
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
        max_reconnect_attempts: int = 0,
        base_url: str = "wss://stream.bybit.com/v5/public/linear",
    ) -> None:
        super().__init__(
            reconnect_seconds=reconnect_seconds,
            max_reconnect_attempts=max_reconnect_attempts,
        )
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

        reconnect_attempts = 0
        while not stop_event.is_set():
            try:
                async with websockets.connect(self.base_url) as websocket:
                    reconnect_attempts = 0
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
                reconnect_attempts += 1
                await on_connection_status(self.name, False, str(exc))
                if not self.can_reconnect(reconnect_attempts):
                    break
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
        max_reconnect_attempts: int = 0,
        base_url: str = "wss://ws.okx.com:8443/ws/v5/public",
    ) -> None:
        super().__init__(
            reconnect_seconds=reconnect_seconds,
            max_reconnect_attempts=max_reconnect_attempts,
        )
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

        reconnect_attempts = 0
        while not stop_event.is_set():
            try:
                async with websockets.connect(self.base_url) as websocket:
                    reconnect_attempts = 0
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
                reconnect_attempts += 1
                await on_connection_status(self.name, False, str(exc))
                if not self.can_reconnect(reconnect_attempts):
                    break
                await _sleep_until_stop(stop_event, self.reconnect_seconds)

        await on_connection_status(self.name, False, None)

    def _subscription_args(self, symbols: tuple[str, ...]) -> list[dict[str, str]]:
        return [
            {"channel": "tickers", "instId": inst_id}
            for inst_id in _okx_inst_ids(symbols)
        ]


class BitgetTickerWebSocketConnector(PublicWebSocketConnector):
    name = "bitget"
    exchange_name = "Bitget"
    data_source = "bitget_public_websocket"

    def __init__(
        self,
        reconnect_seconds: int = 5,
        max_reconnect_attempts: int = 0,
        base_url: str = "wss://ws.bitget.com/v2/ws/public",
    ) -> None:
        super().__init__(
            reconnect_seconds=reconnect_seconds,
            max_reconnect_attempts=max_reconnect_attempts,
        )
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
            await on_connection_status(self.name, False, "No Bitget WebSocket symbols selected")
            return

        subscribe_message = json.dumps(
            {
                "op": "subscribe",
                "args": subscription_args,
            }
        )

        reconnect_attempts = 0
        while not stop_event.is_set():
            try:
                async with websockets.connect(self.base_url) as websocket:
                    reconnect_attempts = 0
                    await websocket.send(subscribe_message)
                    await on_connection_status(self.name, True, None)
                    last_ping_at = datetime.now(timezone.utc)
                    while not stop_event.is_set():
                        try:
                            message = await asyncio.wait_for(websocket.recv(), timeout=1)
                        except TimeoutError:
                            now = datetime.now(timezone.utc)
                            if (now - last_ping_at).total_seconds() >= 30:
                                await websocket.send("ping")
                                last_ping_at = now
                            continue

                        snapshot = parse_bitget_ticker_message(message)
                        if snapshot is not None:
                            await on_snapshot(snapshot)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                reconnect_attempts += 1
                await on_connection_status(self.name, False, str(exc))
                if not self.can_reconnect(reconnect_attempts):
                    break
                await _sleep_until_stop(stop_event, self.reconnect_seconds)

        await on_connection_status(self.name, False, None)

    def _subscription_args(self, symbols: tuple[str, ...]) -> list[dict[str, str]]:
        return [
            {
                "instType": "USDT-FUTURES",
                "channel": "ticker",
                "instId": symbol,
            }
            for symbol in _bitget_symbols(symbols)
        ]


class GateBookTickerWebSocketConnector(PublicWebSocketConnector):
    name = "gate"
    exchange_name = "Gate"
    data_source = "gate_public_websocket"

    def __init__(
        self,
        reconnect_seconds: int = 5,
        max_reconnect_attempts: int = 0,
        base_url: str = "wss://fx-ws.gateio.ws/v4/ws/usdt",
    ) -> None:
        super().__init__(
            reconnect_seconds=reconnect_seconds,
            max_reconnect_attempts=max_reconnect_attempts,
        )
        self.base_url = base_url

    async def listen(
        self,
        symbols: tuple[str, ...],
        on_snapshot: SnapshotHandler,
        on_connection_status: ConnectionStatusHandler,
        stop_event: asyncio.Event,
    ) -> None:
        subscription_payload = self._subscription_payload(symbols)
        if not subscription_payload:
            await on_connection_status(self.name, False, "No Gate WebSocket symbols selected")
            return

        reconnect_attempts = 0
        while not stop_event.is_set():
            try:
                async with websockets.connect(self.base_url) as websocket:
                    reconnect_attempts = 0
                    subscribe_message = json.dumps(
                        {
                            "time": int(time.time()),
                            "channel": "futures.book_ticker",
                            "event": "subscribe",
                            "payload": list(subscription_payload),
                        }
                    )
                    await websocket.send(subscribe_message)
                    await on_connection_status(self.name, True, None)
                    last_ping_at = datetime.now(timezone.utc)
                    while not stop_event.is_set():
                        try:
                            message = await asyncio.wait_for(websocket.recv(), timeout=1)
                        except TimeoutError:
                            now = datetime.now(timezone.utc)
                            if (now - last_ping_at).total_seconds() >= 20:
                                await websocket.send(_gate_ping_message())
                                last_ping_at = now
                            continue

                        snapshot = parse_gate_book_ticker_message(message)
                        if snapshot is not None:
                            await on_snapshot(snapshot)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                reconnect_attempts += 1
                await on_connection_status(self.name, False, str(exc))
                if not self.can_reconnect(reconnect_attempts):
                    break
                await _sleep_until_stop(stop_event, self.reconnect_seconds)

        await on_connection_status(self.name, False, None)

    def _subscription_payload(self, symbols: tuple[str, ...]) -> tuple[str, ...]:
        return _gate_contracts(symbols)


class MexcTickersWebSocketConnector(PublicWebSocketConnector):
    name = "mexc"
    exchange_name = "MEXC"
    data_source = "mexc_public_websocket"

    def __init__(
        self,
        reconnect_seconds: int = 5,
        max_reconnect_attempts: int = 0,
        base_url: str = "wss://contract.mexc.com/edge",
    ) -> None:
        super().__init__(
            reconnect_seconds=reconnect_seconds,
            max_reconnect_attempts=max_reconnect_attempts,
        )
        self.base_url = base_url

    async def listen(
        self,
        symbols: tuple[str, ...],
        on_snapshot: SnapshotHandler,
        on_connection_status: ConnectionStatusHandler,
        stop_event: asyncio.Event,
    ) -> None:
        selected_symbols = _mexc_symbols(symbols)
        if not selected_symbols:
            await on_connection_status(self.name, False, "No MEXC WebSocket symbols selected")
            return

        subscribe_message = self._subscription_message()
        reconnect_attempts = 0
        while not stop_event.is_set():
            try:
                async with websockets.connect(self.base_url) as websocket:
                    reconnect_attempts = 0
                    await websocket.send(subscribe_message)
                    await on_connection_status(self.name, True, None)
                    last_ping_at = datetime.now(timezone.utc)
                    while not stop_event.is_set():
                        try:
                            message = await asyncio.wait_for(websocket.recv(), timeout=1)
                        except TimeoutError:
                            now = datetime.now(timezone.utc)
                            if (now - last_ping_at).total_seconds() >= 15:
                                await websocket.send(_mexc_ping_message())
                                last_ping_at = now
                            continue

                        for snapshot in parse_mexc_tickers_message(
                            message,
                            selected_symbols=selected_symbols,
                        ):
                            await on_snapshot(snapshot)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                reconnect_attempts += 1
                await on_connection_status(self.name, False, str(exc))
                if not self.can_reconnect(reconnect_attempts):
                    break
                await _sleep_until_stop(stop_event, self.reconnect_seconds)

        await on_connection_status(self.name, False, None)

    def _subscription_message(self) -> str:
        return json.dumps(
            {
                "method": "sub.tickers",
                "param": {},
                "gzip": False,
            }
        )


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


def parse_bitget_ticker_message(message: str | bytes) -> MarketSnapshot | None:
    if isinstance(message, bytes):
        stripped_message = message.decode("utf-8").strip()
    else:
        stripped_message = str(message).strip()
    if stripped_message in {"pong", "ping"}:
        return None

    payload = _json_message(stripped_message)
    if not isinstance(payload, dict):
        return None
    if payload.get("event") or payload.get("op"):
        return None

    arg = payload.get("arg") if isinstance(payload.get("arg"), dict) else {}
    if arg.get("instType") not in (None, "USDT-FUTURES"):
        return None
    if arg.get("channel") not in (None, "ticker"):
        return None

    data = payload.get("data")
    if not isinstance(data, list) or not data:
        return None
    ticker = data[0]
    if not isinstance(ticker, dict):
        return None
    if ticker.get("symbolType") not in (None, 1, "1"):
        return None

    symbol = normalize_symbol(
        str(
            ticker.get("symbol")
            or ticker.get("instId")
            or arg.get("instId")
            or ""
        ),
        "Bitget",
    )
    if not symbol:
        return None

    try:
        best_bid = float(ticker["bidPr"])
        best_ask = float(ticker["askPr"])
    except (KeyError, TypeError, ValueError):
        return None

    if best_bid <= 0 or best_ask <= 0:
        return None

    return MarketSnapshot(
        exchange="Bitget",
        symbol=symbol,
        best_bid=best_bid,
        best_bid_size=_float_or_zero(ticker.get("bidSz")),
        best_ask=best_ask,
        best_ask_size=_float_or_zero(ticker.get("askSz")),
        volume_24h_usd=_bitget_volume_24h_usd(ticker),
        funding_rate_percent=_float_or_zero(ticker.get("fundingRate")) * 100,
        next_funding_time=_datetime_from_millis(ticker.get("nextFundingTime")),
        timestamp=_datetime_from_millis(ticker.get("ts") or payload.get("ts"))
        or datetime.now(timezone.utc),
        source="websocket",
    )


def parse_gate_book_ticker_message(message: str | bytes) -> MarketSnapshot | None:
    payload = _json_message(message)
    if not isinstance(payload, dict):
        return None
    if payload.get("channel") not in (None, "futures.book_ticker"):
        return None
    if payload.get("event") not in (None, "update"):
        return None

    result = payload.get("result")
    if not isinstance(result, dict):
        return None

    symbol = normalize_symbol(str(result.get("s", "")), "Gate")
    if not symbol.endswith("USDT") or len(symbol) <= 4:
        return None

    try:
        best_bid = float(result["b"])
        best_ask = float(result["a"])
    except (KeyError, TypeError, ValueError):
        return None

    if best_bid <= 0 or best_ask <= 0:
        return None

    return MarketSnapshot(
        exchange="Gate",
        symbol=symbol,
        best_bid=best_bid,
        best_bid_size=_float_or_zero(result.get("B")),
        best_ask=best_ask,
        best_ask_size=_float_or_zero(result.get("A")),
        volume_24h_usd=0,
        funding_rate_percent=0,
        next_funding_time=None,
        timestamp=_datetime_from_millis(result.get("t") or payload.get("time_ms"))
        or datetime.now(timezone.utc),
        source="websocket",
    )


def parse_mexc_tickers_message(
    message: str | bytes,
    selected_symbols: tuple[str, ...] | None = None,
) -> list[MarketSnapshot]:
    payload = _json_message(message)
    if not isinstance(payload, dict):
        return []
    if payload.get("channel") not in (None, "push.tickers"):
        return []
    if payload.get("method") in {"pong", "ping"}:
        return []

    data = payload.get("data")
    if isinstance(data, dict):
        tickers = [data]
    elif isinstance(data, list):
        tickers = [ticker for ticker in data if isinstance(ticker, dict)]
    else:
        return []

    selected = set(_mexc_symbols(selected_symbols or ()))
    require_selected = selected_symbols is not None
    snapshots: list[MarketSnapshot] = []
    for ticker in tickers:
        symbol = normalize_symbol(str(ticker.get("symbol", "")), "MEXC")
        if not symbol.endswith("USDT") or len(symbol) <= 4:
            continue
        if require_selected and symbol not in selected:
            continue

        try:
            best_bid = float(ticker["maxBidPrice"])
            best_ask = float(ticker["minAskPrice"])
        except (KeyError, TypeError, ValueError):
            continue

        if best_bid <= 0 or best_ask <= 0:
            continue

        snapshots.append(
            MarketSnapshot(
                exchange="MEXC",
                symbol=symbol,
                best_bid=best_bid,
                best_bid_size=_float_or_zero(
                    _first_present(
                        ticker.get("maxBidSize"),
                        ticker.get("bid1Size"),
                        ticker.get("bidSize"),
                    )
                ),
                best_ask=best_ask,
                best_ask_size=_float_or_zero(
                    _first_present(
                        ticker.get("minAskSize"),
                        ticker.get("ask1Size"),
                        ticker.get("askSize"),
                    )
                ),
                volume_24h_usd=_mexc_volume_24h_usd(ticker),
                funding_rate_percent=_float_or_zero(ticker.get("fundingRate")) * 100,
                next_funding_time=None,
                timestamp=_datetime_from_millis(
                    _first_present(
                        ticker.get("timestamp"),
                        payload.get("ts"),
                        payload.get("sendtime"),
                    )
                )
                or datetime.now(timezone.utc),
                source="websocket",
            )
        )

    return snapshots


def build_public_websocket_connectors(
    exchanges: tuple[str, ...],
    reconnect_seconds: int,
    max_reconnect_attempts: int = 0,
) -> list[PublicWebSocketConnector]:
    connectors: list[PublicWebSocketConnector] = []
    enabled = {exchange_name_key(exchange) for exchange in exchanges}
    if "binance" in enabled:
        connectors.append(
            BinanceBookTickerWebSocketConnector(
                reconnect_seconds=reconnect_seconds,
                max_reconnect_attempts=max_reconnect_attempts,
            )
        )
    if "bybit" in enabled:
        connectors.append(
            BybitTickerWebSocketConnector(
                reconnect_seconds=reconnect_seconds,
                max_reconnect_attempts=max_reconnect_attempts,
            )
        )
    if "okx" in enabled:
        connectors.append(
            OKXTickerWebSocketConnector(
                reconnect_seconds=reconnect_seconds,
                max_reconnect_attempts=max_reconnect_attempts,
            )
        )
    if "bitget" in enabled:
        connectors.append(
            BitgetTickerWebSocketConnector(
                reconnect_seconds=reconnect_seconds,
                max_reconnect_attempts=max_reconnect_attempts,
            )
        )
    if "gate" in enabled:
        connectors.append(
            GateBookTickerWebSocketConnector(
                reconnect_seconds=reconnect_seconds,
                max_reconnect_attempts=max_reconnect_attempts,
            )
        )
    if "mexc" in enabled:
        connectors.append(
            MexcTickersWebSocketConnector(
                reconnect_seconds=reconnect_seconds,
                max_reconnect_attempts=max_reconnect_attempts,
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


def _bitget_symbols(symbols: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            symbol
            for symbol in (normalize_symbol(raw_symbol, "Bitget") for raw_symbol in symbols)
            if symbol.endswith("USDT") and len(symbol) > 4
        )
    )


def _gate_contracts(symbols: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            contract
            for contract in (_gate_contract(raw_symbol) for raw_symbol in symbols)
            if contract
        )
    )


def _gate_contract(symbol: str) -> str:
    normalized = normalize_symbol(symbol, "Gate")
    if not normalized.endswith("USDT") or len(normalized) <= 4:
        return ""
    return f"{normalized[:-4]}_USDT"


def _mexc_symbols(symbols: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            symbol
            for symbol in (normalize_symbol(raw_symbol, "MEXC") for raw_symbol in symbols)
            if symbol.endswith("USDT") and len(symbol) > 4
        )
    )


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


def _bitget_volume_24h_usd(ticker: dict[str, Any]) -> float:
    usdt_volume = _float_or_zero(ticker.get("usdtVolume"))
    if usdt_volume > 0:
        return usdt_volume
    return _float_or_zero(ticker.get("quoteVolume"))


def _mexc_volume_24h_usd(ticker: dict[str, Any]) -> float:
    for field in ("amount24", "turnover24h", "quoteVolume", "amount"):
        value = _float_or_zero(ticker.get(field))
        if value > 0:
            return value

    last_price = _float_or_zero(
        _first_present(ticker.get("lastPrice"), ticker.get("fairPrice"))
    )
    base_volume = _float_or_zero(ticker.get("volume24"))
    return last_price * base_volume


def _first_present(*values: object) -> object:
    for value in values:
        if value not in (None, ""):
            return value
    return None


def _gate_ping_message() -> str:
    return json.dumps(
        {
            "time": int(time.time()),
            "channel": "futures.ping",
            "event": "",
            "payload": [],
        }
    )


def _mexc_ping_message() -> str:
    return json.dumps({"method": "ping"})


async def _sleep_until_stop(stop_event: asyncio.Event, seconds: int) -> None:
    try:
        await asyncio.wait_for(stop_event.wait(), timeout=seconds)
    except TimeoutError:
        return
