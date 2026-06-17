import asyncio
import json
from datetime import datetime, timezone
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from app.connectors.base import ExchangeConnector
from app.domain.models import MarketSnapshot, MarketSymbol, OrderBookLevel, OrderBookSnapshot
from app.services.symbols import normalize_symbol


BITGET_PRODUCT_TYPE = "USDT-FUTURES"


class BitgetPublicConnector(ExchangeConnector):
    name = "bitget"
    exchange_name = "Bitget"
    data_source = "bitget_public_rest"

    def __init__(
        self,
        symbol_allowlist: tuple[str, ...],
        max_symbols: int,
        base_url: str = "https://api.bitget.com",
        timeout_seconds: int = 10,
    ) -> None:
        self.symbol_allowlist = tuple(
            normalize_symbol(symbol, "Bitget")
            for symbol in symbol_allowlist
            if normalize_symbol(symbol, "Bitget")
        )
        self.max_symbols = max_symbols
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    async def fetch_snapshots(
        self,
        symbols: tuple[str, ...] | None = None,
    ) -> list[MarketSnapshot]:
        selected_symbols = (
            _normalize_symbol_tuple(symbols, "Bitget")
            if symbols is not None
            else tuple(await self.fetch_symbols())
        )
        if not selected_symbols:
            return []

        tickers_response = await self._get_json(
            "/api/v2/mix/market/tickers",
            {"productType": BITGET_PRODUCT_TYPE},
        )
        tickers = self._ticker_map(tickers_response)
        funding_by_symbol = await self._safe_get_funding_map()

        snapshots: list[MarketSnapshot] = []
        for symbol in selected_symbols:
            ticker = tickers.get(symbol)
            if ticker is None:
                continue
            try:
                snapshots.append(
                    self._snapshot_from_ticker(
                        symbol=symbol,
                        ticker=ticker,
                        funding=funding_by_symbol.get(symbol, {}),
                    )
                )
            except (KeyError, TypeError, ValueError):
                continue

        if selected_symbols and not snapshots:
            raise RuntimeError("No Bitget snapshots could be parsed")

        return snapshots

    async def fetch_symbols(self) -> list[str]:
        contracts_response = await self._get_json(
            "/api/v2/mix/market/contracts",
            {"productType": BITGET_PRODUCT_TYPE},
        )
        return self._symbols_from_contracts(
            contracts_response,
            allowlist=set(self.symbol_allowlist),
            max_symbols=self.max_symbols,
        )

    async def fetch_symbol_markets(self) -> list[MarketSymbol]:
        contracts_response = await self._get_json(
            "/api/v2/mix/market/contracts",
            {"productType": BITGET_PRODUCT_TYPE},
        )
        symbols = self._symbols_from_contracts(contracts_response)
        tickers_response = await self._get_json(
            "/api/v2/mix/market/tickers",
            {"productType": BITGET_PRODUCT_TYPE},
        )
        tickers = self._ticker_map(tickers_response)

        return [
            MarketSymbol(
                exchange="Bitget",
                symbol=symbol,
                volume_24h_usd=_ticker_volume_24h_usd(tickers.get(symbol, {})),
            )
            for symbol in symbols
        ]

    async def fetch_order_book(
        self,
        symbol: str,
        limit: int = 50,
    ) -> OrderBookSnapshot:
        normalized_symbol = normalize_symbol(symbol, "Bitget")
        response = await self._get_json(
            "/api/v2/mix/market/merge-depth",
            {
                "symbol": normalized_symbol,
                "productType": BITGET_PRODUCT_TYPE,
                "precision": "scale0",
                "limit": _bitget_depth_limit(limit),
            },
        )
        data = self._data_object(response)
        bids = _levels_from_raw(data.get("bids", []))
        asks = _levels_from_raw(data.get("asks", []))
        if not bids or not asks:
            raise ValueError("Bitget order book response has no bid/ask levels")

        return OrderBookSnapshot(
            exchange="Bitget",
            symbol=normalized_symbol,
            bids=bids,
            asks=asks,
            timestamp=_datetime_from_millis(data.get("ts")) or datetime.now(timezone.utc),
        )

    def _symbols_from_contracts(
        self,
        response: dict | list,
        allowlist: set[str] | None = None,
        max_symbols: int | None = None,
    ) -> list[str]:
        allowed_symbols = allowlist or set()
        symbols: list[str] = []
        for contract in self._data_list(response):
            symbol = _symbol_from_contract(contract)
            if not symbol:
                continue
            if allowed_symbols and symbol not in allowed_symbols:
                continue

            symbols.append(symbol)
            if max_symbols is not None and len(symbols) >= max_symbols:
                break

        return symbols

    def _ticker_map(self, response: dict | list) -> dict[str, dict]:
        tickers: dict[str, dict] = {}
        for ticker in self._data_list(response):
            symbol = normalize_symbol(str(ticker.get("symbol", "")), "Bitget")
            if symbol:
                tickers[symbol] = ticker
        return tickers

    async def _safe_get_funding_map(self) -> dict[str, dict]:
        try:
            response = await self._get_json(
                "/api/v2/mix/market/current-fund-rate",
                {"productType": BITGET_PRODUCT_TYPE},
            )
            funding_items = self._data_list(response)
        except Exception:
            # Funding is contextual; missing Bitget funding should not block prices.
            return {}

        funding_by_symbol: dict[str, dict] = {}
        for funding in funding_items:
            symbol = normalize_symbol(str(funding.get("symbol", "")), "Bitget")
            if symbol:
                funding_by_symbol[symbol] = funding
        return funding_by_symbol

    def _snapshot_from_ticker(
        self,
        symbol: str,
        ticker: dict,
        funding: dict,
    ) -> MarketSnapshot:
        best_bid = float(ticker["bidPr"])
        best_ask = float(ticker["askPr"])
        if best_bid <= 0 or best_ask <= 0:
            raise ValueError("Bid/ask must be positive")

        return MarketSnapshot(
            exchange="Bitget",
            symbol=normalize_symbol(symbol, "Bitget"),
            best_bid=best_bid,
            best_bid_size=_float_or_zero(ticker.get("bidSz")),
            best_ask=best_ask,
            best_ask_size=_float_or_zero(ticker.get("askSz")),
            volume_24h_usd=_ticker_volume_24h_usd(ticker),
            funding_rate_percent=_float_or_zero(
                _first_present(funding.get("fundingRate"), ticker.get("fundingRate"))
            )
            * 100,
            next_funding_time=_datetime_from_millis(
                _first_present(
                    funding.get("nextUpdate"),
                    funding.get("nextFundingTime"),
                )
            ),
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

    def _data_list(self, response: dict | list) -> list[dict]:
        data = self._data(response)
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
        if isinstance(data, dict):
            return [data]
        raise ValueError("Bitget response data must be a list or object")

    def _data_object(self, response: dict | list) -> dict:
        data = self._data(response)
        if not isinstance(data, dict):
            raise ValueError("Bitget response data must be an object")
        return data

    def _data(self, response: dict | list) -> object:
        if not isinstance(response, dict):
            raise ValueError("Bitget response must be an object")
        if str(response.get("code", "")) != "00000":
            message = response.get("msg") or "unknown Bitget error"
            raise RuntimeError(f"Bitget public request failed: {message}")
        return response.get("data", [])

    # REST-only connector. No auth, private account APIs, or trading APIs here.


def _symbol_from_contract(contract: dict) -> str:
    if str(contract.get("quoteCoin", "")).upper() != "USDT":
        return ""
    if str(contract.get("symbolType", "")).lower() != "perpetual":
        return ""
    if str(contract.get("symbolStatus", "")).lower() != "normal":
        return ""

    symbol = normalize_symbol(str(contract.get("symbol", "")), "Bitget")
    if not symbol.endswith("USDT"):
        return ""
    return symbol


def _ticker_volume_24h_usd(ticker: dict) -> float:
    usdt_volume = _float_or_zero(ticker.get("usdtVolume"))
    if usdt_volume > 0:
        return usdt_volume
    return _float_or_zero(ticker.get("quoteVolume"))


def _bitget_depth_limit(limit: int) -> str:
    if limit <= 1:
        return "1"
    if limit <= 5:
        return "5"
    if limit <= 15:
        return "15"
    if limit <= 50:
        return "50"
    return "max"


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


def _first_present(*values: object) -> object:
    for value in values:
        if value not in (None, ""):
            return value
    return None


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
