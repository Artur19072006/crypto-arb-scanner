import asyncio
import json
from datetime import datetime, timezone
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from app.connectors.base import ExchangeConnector
from app.domain.models import MarketSnapshot
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

    async def fetch_snapshots(self) -> list[MarketSnapshot]:
        symbols = await self.fetch_symbols()
        snapshots: list[MarketSnapshot] = []

        for symbol in symbols:
            snapshot = await self._fetch_symbol_snapshot(symbol)
            if snapshot is not None:
                snapshots.append(snapshot)

        if symbols and not snapshots:
            raise RuntimeError("No Binance snapshots could be parsed")

        return snapshots

    async def fetch_symbols(self) -> list[str]:
        exchange_info = await self._get_json("/fapi/v1/exchangeInfo")
        raw_symbols = exchange_info.get("symbols", [])
        allowlist = set(self.symbol_allowlist)

        symbols: list[str] = []
        for raw_symbol in raw_symbols:
            if raw_symbol.get("contractType") != "PERPETUAL":
                continue
            if raw_symbol.get("status") != "TRADING":
                continue
            if raw_symbol.get("quoteAsset") != "USDT":
                continue

            symbol = normalize_symbol(str(raw_symbol.get("symbol", "")), "Binance")
            if not symbol:
                continue
            if allowlist and symbol not in allowlist:
                continue

            symbols.append(symbol)

            if len(symbols) >= self.max_symbols:
                break

        return symbols

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
