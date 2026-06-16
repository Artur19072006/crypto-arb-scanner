import asyncio
import json
from datetime import datetime, timezone
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from app.connectors.base import ExchangeConnector
from app.domain.models import MarketSnapshot, MarketSymbol
from app.services.symbols import normalize_symbol


class BinancePublicConnector(ExchangeConnector):
    name = "binance"
    data_source = "binance_public_rest"

    def __init__(
        self,
        symbol_allowlist: tuple[str, ...],
        max_symbols: int,
        base_url: str = "https://fapi.binance.com",
        timeout_seconds: int = 10,
    ) -> None:
        self.symbol_allowlist = tuple(
            normalize_symbol(symbol)
            for symbol in symbol_allowlist
            if normalize_symbol(symbol)
        )
        self.max_symbols = max_symbols
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    async def fetch_snapshots(
        self,
        symbols: tuple[str, ...] | None = None,
    ) -> list[MarketSnapshot]:
        selected_symbols = (
            _normalize_symbol_tuple(symbols, "Binance")
            if symbols is not None
            else tuple(await self.fetch_symbols())
        )
        snapshots: list[MarketSnapshot] = []
        bulk_snapshots = await self._fetch_bulk_snapshots(selected_symbols)
        if bulk_snapshots is not None:
            snapshots = bulk_snapshots
        else:
            for symbol in selected_symbols:
                snapshot = await self._fetch_symbol_snapshot(symbol)
                if snapshot is not None:
                    snapshots.append(snapshot)

        if selected_symbols and not snapshots:
            raise RuntimeError("No Binance snapshots could be parsed")

        return snapshots

    async def fetch_symbols(self) -> list[str]:
        exchange_info = await self._get_json("/fapi/v1/exchangeInfo")
        allowlist = set(self.symbol_allowlist)
        return self._symbols_from_exchange_info(
            exchange_info,
            allowlist=allowlist,
            max_symbols=self.max_symbols,
        )

    async def fetch_symbol_markets(self) -> list[MarketSymbol]:
        exchange_info = await self._get_json("/fapi/v1/exchangeInfo")
        symbols = self._symbols_from_exchange_info(exchange_info)
        volume_tickers = await self._get_json("/fapi/v1/ticker/24hr")
        volume_by_symbol = self._volume_by_symbol(volume_tickers)

        return [
            MarketSymbol(
                exchange="Binance",
                symbol=symbol,
                volume_24h_usd=volume_by_symbol.get(symbol, 0.0),
            )
            for symbol in symbols
        ]

    async def _fetch_bulk_snapshots(
        self,
        symbols: tuple[str, ...],
    ) -> list[MarketSnapshot] | None:
        if not symbols:
            return []

        try:
            book_tickers = await self._get_json("/fapi/v1/ticker/bookTicker")
            volume_tickers = await self._get_json("/fapi/v1/ticker/24hr")
            funding_tickers = await self._safe_get_all_funding()
        except Exception:
            return None

        book_by_symbol = self._object_by_symbol(book_tickers)
        volume_by_symbol = self._object_by_symbol(volume_tickers)
        funding_by_symbol = self._object_by_symbol(funding_tickers)

        snapshots: list[MarketSnapshot] = []
        for symbol in symbols:
            book_ticker = book_by_symbol.get(symbol)
            volume_ticker = volume_by_symbol.get(symbol)
            if book_ticker is None or volume_ticker is None:
                continue

            try:
                snapshots.append(
                    self._snapshot_from_responses(
                        symbol=symbol,
                        book_ticker=book_ticker,
                        volume_ticker=volume_ticker,
                        funding=funding_by_symbol.get(symbol, {}),
                    )
                )
            except (KeyError, TypeError, ValueError):
                continue

        return snapshots

    def _object_by_symbol(self, response: dict | list) -> dict[str, dict]:
        raw_items = response if isinstance(response, list) else [response]
        items_by_symbol: dict[str, dict] = {}
        for raw_item in raw_items:
            if not isinstance(raw_item, dict):
                continue
            symbol = normalize_symbol(str(raw_item.get("symbol", "")), "Binance")
            if symbol:
                items_by_symbol[symbol] = raw_item
        return items_by_symbol

    def _symbols_from_exchange_info(
        self,
        exchange_info: dict | list,
        allowlist: set[str] | None = None,
        max_symbols: int | None = None,
    ) -> list[str]:
        if not isinstance(exchange_info, dict):
            return []

        raw_symbols = exchange_info.get("symbols", [])
        allowed_symbols = allowlist or set()
        symbols: list[str] = []
        for raw_symbol in raw_symbols:
            if not isinstance(raw_symbol, dict):
                continue
            if raw_symbol.get("contractType") != "PERPETUAL":
                continue
            if raw_symbol.get("status") != "TRADING":
                continue
            if raw_symbol.get("quoteAsset") != "USDT":
                continue

            symbol = normalize_symbol(str(raw_symbol.get("symbol", "")), "Binance")
            if not symbol:
                continue
            if allowed_symbols and symbol not in allowed_symbols:
                continue

            symbols.append(symbol)

            if max_symbols is not None and len(symbols) >= max_symbols:
                break

        return symbols

    def _volume_by_symbol(self, response: dict | list) -> dict[str, float]:
        raw_tickers = response if isinstance(response, list) else [response]
        volume_by_symbol: dict[str, float] = {}
        for raw_ticker in raw_tickers:
            if not isinstance(raw_ticker, dict):
                continue
            symbol = normalize_symbol(str(raw_ticker.get("symbol", "")), "Binance")
            if not symbol:
                continue
            volume_by_symbol[symbol] = _float_or_zero(raw_ticker.get("quoteVolume"))
        return volume_by_symbol

    async def _fetch_symbol_snapshot(self, symbol: str) -> MarketSnapshot | None:
        try:
            book_ticker = await self._get_json(
                "/fapi/v1/ticker/bookTicker",
                {"symbol": symbol},
            )
            volume_ticker = await self._get_json(
                "/fapi/v1/ticker/24hr",
                {"symbol": symbol},
            )
            funding = await self._safe_get_funding(symbol)

            return self._snapshot_from_responses(
                symbol=symbol,
                book_ticker=book_ticker,
                volume_ticker=volume_ticker,
                funding=funding,
            )
        except Exception:
            return None

    async def _safe_get_funding(self, symbol: str) -> dict:
        try:
            funding = await self._get_json("/fapi/v1/premiumIndex", {"symbol": symbol})
        except Exception:
            # Funding is useful context, but missing funding should not block snapshots.
            # TODO: Add richer Binance funding handling when alert logic is implemented.
            return {}

        return funding if isinstance(funding, dict) else {}

    async def _safe_get_all_funding(self) -> dict | list:
        try:
            funding = await self._get_json("/fapi/v1/premiumIndex")
        except Exception:
            # Funding is useful context, but missing funding should not block snapshots.
            return []

        return funding if isinstance(funding, (dict, list)) else []

    def _snapshot_from_responses(
        self,
        symbol: str,
        book_ticker: dict,
        volume_ticker: dict,
        funding: dict,
    ) -> MarketSnapshot:
        best_bid = float(book_ticker["bidPrice"])
        best_ask = float(book_ticker["askPrice"])
        if best_bid <= 0 or best_ask <= 0:
            raise ValueError("Bid/ask must be positive")

        return MarketSnapshot(
            exchange="Binance",
            symbol=normalize_symbol(symbol, "Binance"),
            best_bid=best_bid,
            best_bid_size=float(book_ticker.get("bidQty", 0)),
            best_ask=best_ask,
            best_ask_size=float(book_ticker.get("askQty", 0)),
            volume_24h_usd=float(volume_ticker.get("quoteVolume", 0)),
            funding_rate_percent=float(funding.get("lastFundingRate", 0)) * 100,
            next_funding_time=_datetime_from_millis(funding.get("nextFundingTime")),
            timestamp=_datetime_from_millis(book_ticker.get("time")) or datetime.now(timezone.utc),
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

    # TODO: Add Binance USD-M Futures WebSocket ticker/book stream support later.
    # TODO: Keep WebSocket support public-market-data only; no private streams/API keys.


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
