import asyncio
import json
from datetime import datetime, timezone
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from app.connectors.base import ExchangeConnector
from app.domain.models import MarketSnapshot, MarketSymbol, OrderBookLevel, OrderBookSnapshot
from app.services.symbols import normalize_symbol


class OKXPublicConnector(ExchangeConnector):
    name = "okx"
    exchange_name = "OKX"
    data_source = "okx_public_rest"

    def __init__(
        self,
        symbol_allowlist: tuple[str, ...],
        max_symbols: int,
        base_url: str = "https://www.okx.com",
        timeout_seconds: int = 10,
        funding_concurrency: int = 8,
    ) -> None:
        self.symbol_allowlist = tuple(
            normalize_symbol(symbol, "OKX")
            for symbol in symbol_allowlist
            if normalize_symbol(symbol, "OKX")
        )
        self.max_symbols = max_symbols
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.funding_concurrency = funding_concurrency

    async def fetch_snapshots(
        self,
        symbols: tuple[str, ...] | None = None,
    ) -> list[MarketSnapshot]:
        selected_symbols = (
            _normalize_symbol_tuple(symbols, "OKX")
            if symbols is not None
            else tuple(await self.fetch_symbols())
        )
        if not selected_symbols:
            return []

        instruments_response = await self._get_json(
            "/api/v5/public/instruments",
            {"instType": "SWAP"},
        )
        instrument_by_symbol = self._instrument_by_symbol(instruments_response)
        selected_inst_ids = {
            symbol: instrument["instId"]
            for symbol, instrument in instrument_by_symbol.items()
            if symbol in selected_symbols
        }
        if not selected_inst_ids:
            return []

        tickers_response = await self._get_json(
            "/api/v5/market/tickers",
            {"instType": "SWAP"},
        )
        tickers = self._ticker_map(tickers_response)
        funding_by_inst_id = await self._safe_get_funding_map(
            tuple(selected_inst_ids.values())
        )

        snapshots: list[MarketSnapshot] = []
        for symbol in selected_symbols:
            inst_id = selected_inst_ids.get(symbol)
            if not inst_id:
                continue
            ticker = tickers.get(inst_id)
            if not ticker:
                continue
            try:
                snapshots.append(
                    self._snapshot_from_ticker(
                        symbol=symbol,
                        ticker=ticker,
                        funding=funding_by_inst_id.get(inst_id, {}),
                    )
                )
            except (KeyError, TypeError, ValueError):
                continue

        if selected_symbols and selected_inst_ids and not snapshots:
            raise RuntimeError("No OKX snapshots could be parsed")

        return snapshots

    async def fetch_symbols(self) -> list[str]:
        allowlist = set(self.symbol_allowlist)
        instruments_response = await self._get_json(
            "/api/v5/public/instruments",
            {"instType": "SWAP"},
        )
        return self._symbols_from_instruments(
            instruments_response,
            allowlist=allowlist,
            max_symbols=self.max_symbols,
        )

    async def fetch_symbol_markets(self) -> list[MarketSymbol]:
        instruments_response = await self._get_json(
            "/api/v5/public/instruments",
            {"instType": "SWAP"},
        )
        symbols = self._symbols_from_instruments(instruments_response)
        tickers_response = await self._get_json(
            "/api/v5/market/tickers",
            {"instType": "SWAP"},
        )
        tickers = self._ticker_map(tickers_response)

        return [
            MarketSymbol(
                exchange="OKX",
                symbol=symbol,
                volume_24h_usd=_ticker_volume_24h_usd(
                    tickers.get(_okx_inst_id(symbol), {})
                ),
            )
            for symbol in symbols
        ]

    async def fetch_order_book(
        self,
        symbol: str,
        limit: int = 50,
    ) -> OrderBookSnapshot:
        normalized_symbol = normalize_symbol(symbol, "OKX")
        inst_id = _okx_inst_id(normalized_symbol)
        response = await self._get_json(
            "/api/v5/market/books",
            {"instId": inst_id, "sz": str(limit)},
        )
        data = self._data(response)
        if not data:
            raise ValueError("OKX order book response has no data")

        quantity_multiplier = await self._contract_quantity_multiplier(inst_id)
        book = data[0]
        bids = _levels_from_raw(book.get("bids", []), quantity_multiplier)
        asks = _levels_from_raw(book.get("asks", []), quantity_multiplier)
        if not bids or not asks:
            raise ValueError("OKX order book response has no bid/ask levels")

        return OrderBookSnapshot(
            exchange="OKX",
            symbol=normalized_symbol,
            bids=bids,
            asks=asks,
            timestamp=_datetime_from_millis(book.get("ts")) or datetime.now(timezone.utc),
        )

    async def _contract_quantity_multiplier(self, inst_id: str) -> float:
        try:
            response = await self._get_json(
                "/api/v5/public/instruments",
                {"instType": "SWAP", "instId": inst_id},
            )
            data = self._data(response)
        except Exception:
            return 1.0

        instrument = data[0] if data else {}
        contract_value = _float_or_zero(instrument.get("ctVal"))
        return contract_value if contract_value > 0 else 1.0

    def _symbols_from_instruments(
        self,
        response: dict | list,
        allowlist: set[str] | None = None,
        max_symbols: int | None = None,
    ) -> list[str]:
        allowed_symbols = allowlist or set()
        symbols: list[str] = []
        for instrument in self._data(response):
            symbol = _symbol_from_instrument(instrument)
            if not symbol:
                continue
            if allowed_symbols and symbol not in allowed_symbols:
                continue

            symbols.append(symbol)
            if max_symbols is not None and len(symbols) >= max_symbols:
                break

        return symbols

    def _instrument_by_symbol(self, response: dict | list) -> dict[str, dict]:
        instruments: dict[str, dict] = {}
        for instrument in self._data(response):
            symbol = _symbol_from_instrument(instrument)
            if symbol:
                instruments[symbol] = instrument
        return instruments

    def _ticker_map(self, response: dict | list) -> dict[str, dict]:
        tickers: dict[str, dict] = {}
        for ticker in self._data(response):
            inst_id = str(ticker.get("instId", ""))
            if inst_id:
                tickers[inst_id] = ticker
        return tickers

    async def _safe_get_funding_map(
        self,
        inst_ids: tuple[str, ...],
    ) -> dict[str, dict]:
        semaphore = asyncio.Semaphore(self.funding_concurrency)

        async def fetch_one(inst_id: str) -> tuple[str, dict]:
            async with semaphore:
                return inst_id, await self._safe_get_funding(inst_id)

        results = await asyncio.gather(
            *(fetch_one(inst_id) for inst_id in inst_ids),
            return_exceptions=True,
        )
        funding_by_inst_id: dict[str, dict] = {}
        for result in results:
            if isinstance(result, Exception):
                continue
            inst_id, funding = result
            funding_by_inst_id[inst_id] = funding
        return funding_by_inst_id

    async def _safe_get_funding(self, inst_id: str) -> dict:
        try:
            response = await self._get_json(
                "/api/v5/public/funding-rate",
                {"instId": inst_id},
            )
            data = self._data(response)
        except Exception:
            # Funding is contextual; missing OKX funding should not block prices.
            # TODO: Surface per-connector funding failures separately from price failures.
            return {}

        return data[0] if data else {}

    def _snapshot_from_ticker(
        self,
        symbol: str,
        ticker: dict,
        funding: dict,
    ) -> MarketSnapshot:
        best_bid = float(ticker["bidPx"])
        best_ask = float(ticker["askPx"])
        if best_bid <= 0 or best_ask <= 0:
            raise ValueError("Bid/ask must be positive")

        return MarketSnapshot(
            exchange="OKX",
            symbol=normalize_symbol(symbol, "OKX"),
            best_bid=best_bid,
            best_bid_size=_float_or_zero(ticker.get("bidSz")),
            best_ask=best_ask,
            best_ask_size=_float_or_zero(ticker.get("askSz")),
            volume_24h_usd=_ticker_volume_24h_usd(ticker),
            funding_rate_percent=_float_or_zero(funding.get("fundingRate")) * 100,
            next_funding_time=_datetime_from_millis(funding.get("nextFundingTime")),
            timestamp=_datetime_from_millis(ticker.get("ts")) or datetime.now(timezone.utc),
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

    def _data(self, response: dict | list) -> list[dict]:
        if not isinstance(response, dict):
            raise ValueError("OKX response must be an object")
        if str(response.get("code", "")) != "0":
            message = response.get("msg") or "unknown OKX error"
            raise RuntimeError(f"OKX public request failed: {message}")

        data = response.get("data", [])
        if not isinstance(data, list):
            raise ValueError("OKX response data must be a list")
        return [item for item in data if isinstance(item, dict)]

    # TODO: Keep OKX support public-market-data only; no private streams/API keys.


def _symbol_from_instrument(instrument: dict) -> str:
    if instrument.get("instType") != "SWAP":
        return ""
    if instrument.get("settleCcy") != "USDT":
        return ""
    if instrument.get("state") != "live":
        return ""

    inst_id = str(instrument.get("instId", ""))
    if not inst_id.endswith("-USDT-SWAP"):
        return ""
    return normalize_symbol(inst_id, "OKX")


def _ticker_volume_24h_usd(ticker: dict) -> float:
    # OKX derivative ticker volume is notionalized here for scanner filtering.
    # volCcy24h is treated as base currency volume and multiplied by last price.
    last_price = _float_or_zero(ticker.get("last"))
    base_volume = _float_or_zero(ticker.get("volCcy24h"))
    return last_price * base_volume


def _okx_inst_id(symbol: str) -> str:
    normalized = normalize_symbol(symbol, "OKX")
    if not normalized.endswith("USDT"):
        return normalized
    return f"{normalized[:-4]}-USDT-SWAP"


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


def _levels_from_raw(
    raw_levels: object,
    quantity_multiplier: float = 1.0,
) -> list[OrderBookLevel]:
    if not isinstance(raw_levels, list):
        return []

    levels: list[OrderBookLevel] = []
    for raw_level in raw_levels:
        if not isinstance(raw_level, (list, tuple)) or len(raw_level) < 2:
            continue
        try:
            price = float(raw_level[0])
            quantity = float(raw_level[1]) * quantity_multiplier
        except (TypeError, ValueError):
            continue
        if price <= 0 or quantity <= 0:
            continue
        levels.append(OrderBookLevel(price=price, quantity=quantity))
    return levels
