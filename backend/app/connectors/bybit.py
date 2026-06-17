import asyncio
import json
from datetime import datetime, timezone
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from app.connectors.base import ExchangeConnector
from app.domain.models import MarketSnapshot, MarketSymbol, OrderBookLevel, OrderBookSnapshot
from app.services.symbols import normalize_symbol


class BybitPublicConnector(ExchangeConnector):
    name = "bybit"
    exchange_name = "Bybit"
    data_source = "bybit_public_rest"

    def __init__(
        self,
        symbol_allowlist: tuple[str, ...],
        max_symbols: int,
        base_url: str = "https://api.bybit.com",
        timeout_seconds: int = 10,
    ) -> None:
        self.symbol_allowlist = tuple(
            normalize_symbol(symbol, "Bybit")
            for symbol in symbol_allowlist
            if normalize_symbol(symbol, "Bybit")
        )
        self.max_symbols = max_symbols
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    async def fetch_snapshots(
        self,
        symbols: tuple[str, ...] | None = None,
    ) -> list[MarketSnapshot]:
        selected_symbols = (
            _normalize_symbol_tuple(symbols, "Bybit")
            if symbols is not None
            else tuple(await self.fetch_symbols())
        )
        if not selected_symbols:
            return []

        tickers_response = await self._get_json(
            "/v5/market/tickers",
            {"category": "linear"},
        )
        tickers = self._ticker_map(tickers_response)

        snapshots: list[MarketSnapshot] = []
        for symbol in selected_symbols:
            ticker = tickers.get(symbol)
            if not ticker:
                continue
            try:
                snapshots.append(
                    self._snapshot_from_ticker(
                        symbol=symbol,
                        ticker=ticker,
                        response_time=tickers_response.get("time")
                        if isinstance(tickers_response, dict)
                        else None,
                    )
                )
            except (KeyError, TypeError, ValueError):
                continue

        if selected_symbols and not snapshots:
            raise RuntimeError("No Bybit snapshots could be parsed")

        return snapshots

    async def fetch_symbols(self) -> list[str]:
        allowlist = set(self.symbol_allowlist)
        symbols = await self._fetch_instrument_symbols(
            allowlist=allowlist,
            max_symbols=self.max_symbols,
        )
        return symbols

    async def fetch_symbol_markets(self) -> list[MarketSymbol]:
        symbols = await self._fetch_instrument_symbols()
        tickers_response = await self._get_json(
            "/v5/market/tickers",
            {"category": "linear"},
        )
        tickers = self._ticker_map(tickers_response)

        return [
            MarketSymbol(
                exchange="Bybit",
                symbol=symbol,
                volume_24h_usd=_float_or_zero(tickers.get(symbol, {}).get("turnover24h")),
            )
            for symbol in symbols
        ]

    async def fetch_order_book(
        self,
        symbol: str,
        limit: int = 50,
    ) -> OrderBookSnapshot:
        normalized_symbol = normalize_symbol(symbol, "Bybit")
        response = await self._get_json(
            "/v5/market/orderbook",
            {
                "category": "linear",
                "symbol": normalized_symbol,
                "limit": str(limit),
            },
        )
        result = self._result(response)
        bids = _levels_from_raw(result.get("b", []))
        asks = _levels_from_raw(result.get("a", []))
        if not bids or not asks:
            raise ValueError("Bybit order book response has no bid/ask levels")

        return OrderBookSnapshot(
            exchange="Bybit",
            symbol=normalize_symbol(str(result.get("s") or normalized_symbol), "Bybit"),
            bids=bids,
            asks=asks,
            timestamp=(
                _datetime_from_millis(result.get("ts"))
                or _datetime_from_millis(response.get("time"))
                if isinstance(response, dict)
                else None
            )
            or datetime.now(timezone.utc),
        )

    async def _fetch_instrument_symbols(
        self,
        allowlist: set[str] | None = None,
        max_symbols: int | None = None,
    ) -> list[str]:
        allowed_symbols = allowlist or set()
        symbols: list[str] = []
        cursor = ""

        while True:
            params = {"category": "linear", "limit": "1000"}
            if cursor:
                params["cursor"] = cursor

            response = await self._get_json("/v5/market/instruments-info", params)
            result = self._result(response)
            for raw_symbol in result.get("list", []):
                if raw_symbol.get("contractType") != "LinearPerpetual":
                    continue
                if raw_symbol.get("status") != "Trading":
                    continue
                if raw_symbol.get("quoteCoin") != "USDT":
                    continue

                symbol = normalize_symbol(str(raw_symbol.get("symbol", "")), "Bybit")
                if not symbol:
                    continue
                if allowed_symbols and symbol not in allowed_symbols:
                    continue

                symbols.append(symbol)
                if max_symbols is not None and len(symbols) >= max_symbols:
                    return symbols

            cursor = str(result.get("nextPageCursor") or "")
            if not cursor:
                return symbols

    def _ticker_map(self, response: dict | list) -> dict[str, dict]:
        result = self._result(response)
        tickers: dict[str, dict] = {}
        for raw_ticker in result.get("list", []):
            symbol = normalize_symbol(str(raw_ticker.get("symbol", "")), "Bybit")
            if symbol:
                tickers[symbol] = raw_ticker
        return tickers

    def _snapshot_from_ticker(
        self,
        symbol: str,
        ticker: dict,
        response_time: object,
    ) -> MarketSnapshot:
        best_bid = float(ticker["bid1Price"])
        best_ask = float(ticker["ask1Price"])
        if best_bid <= 0 or best_ask <= 0:
            raise ValueError("Bid/ask must be positive")

        return MarketSnapshot(
            exchange="Bybit",
            symbol=normalize_symbol(symbol, "Bybit"),
            best_bid=best_bid,
            best_bid_size=_float_or_zero(ticker.get("bid1Size")),
            best_ask=best_ask,
            best_ask_size=_float_or_zero(ticker.get("ask1Size")),
            volume_24h_usd=_float_or_zero(ticker.get("turnover24h")),
            funding_rate_percent=_float_or_zero(ticker.get("fundingRate")) * 100,
            next_funding_time=_datetime_from_millis(ticker.get("nextFundingTime")),
            timestamp=_datetime_from_millis(response_time) or datetime.now(timezone.utc),
        )

    async def _get_json(
        self,
        path: str,
        params: dict[str, str] | None = None,
    ) -> dict | list:
        return await asyncio.to_thread(self._get_json_sync, path, params)

    def _get_json_sync(
        self,
        path: str,
        params: dict[str, str] | None = None,
    ) -> dict | list:
        query = f"?{urlencode(params)}" if params else ""
        url = f"{self.base_url}{path}{query}"
        request = Request(url, headers={"User-Agent": "crypto-arb-scanner/0.1"})

        with urlopen(request, timeout=self.timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8"))

    def _result(self, response: dict | list) -> dict:
        if not isinstance(response, dict):
            raise ValueError("Bybit response must be an object")
        if int(response.get("retCode", 0)) != 0:
            message = response.get("retMsg") or "unknown Bybit error"
            raise RuntimeError(f"Bybit public request failed: {message}")

        result = response.get("result", {})
        if not isinstance(result, dict):
            raise ValueError("Bybit response result must be an object")
        return result

    # Public WebSocket top-of-book support lives in app.connectors.websocket.


def _datetime_from_millis(value: object) -> datetime | None:
    if value in (None, "", 0, "0"):
        return None

    return datetime.fromtimestamp(int(value) / 1000, tz=timezone.utc)


def _normalize_symbol_tuple(
    symbols: tuple[str, ...],
    exchange: str,
) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            symbol
            for symbol in (normalize_symbol(raw_symbol, exchange) for raw_symbol in symbols)
            if symbol
        )
    )


def _float_or_zero(value: object) -> float:
    if value in (None, ""):
        return 0.0

    return float(value)


def _levels_from_raw(raw_levels: object) -> list[OrderBookLevel]:
    if not isinstance(raw_levels, list):
        return []

    levels: list[OrderBookLevel] = []
    for raw_level in raw_levels:
        if not isinstance(raw_level, (list, tuple)) or len(raw_level) < 2:
            continue
        try:
            price = float(raw_level[0])
            quantity = float(raw_level[1])
        except (TypeError, ValueError):
            continue
        if price <= 0 or quantity <= 0:
            continue
        levels.append(OrderBookLevel(price=price, quantity=quantity))
    return levels
