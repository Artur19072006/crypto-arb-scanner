import asyncio
import json
from datetime import datetime, timezone
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from app.connectors.base import ExchangeConnector
from app.domain.models import MarketSnapshot, MarketSymbol, OrderBookLevel, OrderBookSnapshot
from app.services.symbols import normalize_symbol


class MexcPublicConnector(ExchangeConnector):
    name = "mexc"
    exchange_name = "MEXC"
    data_source = "mexc_public_rest"

    def __init__(
        self,
        symbol_allowlist: tuple[str, ...],
        max_symbols: int,
        base_url: str = "https://contract.mexc.com",
        timeout_seconds: int = 10,
    ) -> None:
        self.symbol_allowlist = tuple(
            normalize_symbol(symbol, "MEXC")
            for symbol in symbol_allowlist
            if normalize_symbol(symbol, "MEXC")
        )
        self.max_symbols = max_symbols
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    async def fetch_snapshots(
        self,
        symbols: tuple[str, ...] | None = None,
    ) -> list[MarketSnapshot]:
        selected_symbols = (
            _normalize_symbol_tuple(symbols, "MEXC")
            if symbols is not None
            else tuple(await self.fetch_symbols())
        )
        if not selected_symbols:
            return []

        contracts_response = await self._get_json("/api/v1/contract/detail")
        contracts_by_symbol = self._contract_map(contracts_response)
        selected_contracts = {
            symbol: contracts_by_symbol[symbol]
            for symbol in selected_symbols
            if symbol in contracts_by_symbol
        }
        if not selected_contracts:
            return []

        tickers_response = await self._get_json("/api/v1/contract/ticker")
        tickers = self._ticker_map(tickers_response)

        snapshots: list[MarketSnapshot] = []
        for symbol in selected_contracts:
            ticker = tickers.get(symbol)
            if ticker is None:
                continue
            try:
                snapshots.append(self._snapshot_from_ticker(symbol, ticker))
            except (KeyError, TypeError, ValueError):
                continue

        if selected_contracts and not snapshots:
            raise RuntimeError("No MEXC snapshots could be parsed")

        return snapshots

    async def fetch_symbols(self) -> list[str]:
        contracts_response = await self._get_json("/api/v1/contract/detail")
        return self._symbols_from_contracts(
            contracts_response,
            allowlist=set(self.symbol_allowlist),
            max_symbols=self.max_symbols,
        )

    async def fetch_symbol_markets(self) -> list[MarketSymbol]:
        contracts_response = await self._get_json("/api/v1/contract/detail")
        symbols = self._symbols_from_contracts(contracts_response)
        tickers_response = await self._get_json("/api/v1/contract/ticker")
        tickers = self._ticker_map(tickers_response)

        return [
            MarketSymbol(
                exchange="MEXC",
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
        normalized_symbol = normalize_symbol(symbol, "MEXC")
        contract_symbol = _mexc_contract(normalized_symbol)
        if not contract_symbol:
            raise ValueError(f"Unsupported MEXC symbol: {symbol}")

        contract_size = await self._contract_size(contract_symbol)
        response = await self._get_json(
            f"/api/v1/contract/depth/{contract_symbol}",
            {"limit": str(max(1, limit))},
        )
        data = self._data_object(response)
        bids = _levels_from_raw(data.get("bids", []), contract_size)
        asks = _levels_from_raw(data.get("asks", []), contract_size)
        if not bids or not asks:
            raise ValueError("MEXC order book response has no bid/ask levels")

        return OrderBookSnapshot(
            exchange="MEXC",
            symbol=normalized_symbol,
            bids=bids,
            asks=asks,
            timestamp=_datetime_from_millis(data.get("timestamp")) or datetime.now(timezone.utc),
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

    def _contract_map(self, response: dict | list) -> dict[str, dict]:
        contracts: dict[str, dict] = {}
        for contract in self._data_list(response):
            symbol = _symbol_from_contract(contract)
            if symbol:
                contracts[symbol] = contract
        return contracts

    def _ticker_map(self, response: dict | list) -> dict[str, dict]:
        tickers: dict[str, dict] = {}
        for ticker in self._data_list(response):
            symbol = normalize_symbol(str(ticker.get("symbol", "")), "MEXC")
            if symbol:
                tickers[symbol] = ticker
        return tickers

    def _snapshot_from_ticker(
        self,
        symbol: str,
        ticker: dict,
    ) -> MarketSnapshot:
        best_bid = float(ticker["bid1"])
        best_ask = float(ticker["ask1"])
        if best_bid <= 0 or best_ask <= 0:
            raise ValueError("Bid/ask must be positive")

        return MarketSnapshot(
            exchange="MEXC",
            symbol=normalize_symbol(symbol, "MEXC"),
            best_bid=best_bid,
            best_bid_size=_float_or_zero(
                _first_present(ticker.get("bid1Size"), ticker.get("bidSize"))
            ),
            best_ask=best_ask,
            best_ask_size=_float_or_zero(
                _first_present(ticker.get("ask1Size"), ticker.get("askSize"))
            ),
            volume_24h_usd=_ticker_volume_24h_usd(ticker),
            funding_rate_percent=_float_or_zero(ticker.get("fundingRate")) * 100,
            next_funding_time=None,
            timestamp=_datetime_from_millis(ticker.get("timestamp")) or datetime.now(timezone.utc),
        )

    async def _contract_size(self, contract_symbol: str) -> float:
        response = await self._get_json(
            "/api/v1/contract/detail",
            {"symbol": contract_symbol},
        )
        for contract in self._data_list(response):
            if _mexc_contract_name(str(contract.get("symbol", ""))) == contract_symbol:
                contract_size = _float_or_zero(contract.get("contractSize"))
                if contract_size > 0:
                    return contract_size
        raise ValueError(f"MEXC contract size unavailable for {contract_symbol}")

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
        raise ValueError("MEXC response data must be a list or object")

    def _data_object(self, response: dict | list) -> dict:
        data = self._data(response)
        if not isinstance(data, dict):
            raise ValueError("MEXC response data must be an object")
        return data

    def _data(self, response: dict | list) -> object:
        if not isinstance(response, dict):
            raise ValueError("MEXC response must be an object")
        if response.get("success") is False or int(response.get("code", 0)) != 0:
            message = response.get("message") or "unknown MEXC error"
            raise RuntimeError(f"MEXC public request failed: {message}")
        if "data" in response:
            return response["data"]
        return response

    # REST-only connector. No auth, private account APIs, WebSocket, or trading APIs here.


def _symbol_from_contract(contract: dict) -> str:
    contract_symbol = _mexc_contract_name(str(contract.get("symbol", "")))
    if not contract_symbol:
        return ""
    if str(contract.get("quoteCoin", "")).upper() != "USDT":
        return ""
    if str(contract.get("settleCoin", "")).upper() != "USDT":
        return ""
    if int(contract.get("state", 0)) != 0:
        return ""
    if _truthy(contract.get("isHidden")):
        return ""

    symbol = normalize_symbol(contract_symbol, "MEXC")
    if not symbol.endswith("USDT"):
        return ""
    return symbol


def _mexc_contract_name(value: str) -> str:
    contract_name = value.upper().strip().replace("-", "_")
    parts = contract_name.split("_")
    if len(parts) != 2 or parts[1] != "USDT" or not parts[0]:
        return ""
    return contract_name


def _mexc_contract(symbol: str) -> str:
    normalized_symbol = normalize_symbol(symbol, "MEXC")
    if not normalized_symbol.endswith("USDT") or len(normalized_symbol) <= 4:
        return ""
    return f"{normalized_symbol[:-4]}_USDT"


def _ticker_volume_24h_usd(ticker: dict) -> float:
    amount = _float_or_zero(ticker.get("amount24"))
    if amount > 0:
        return amount

    last_price = _float_or_zero(
        _first_present(ticker.get("lastPrice"), ticker.get("fairPrice"))
    )
    base_volume = _float_or_zero(ticker.get("volume24"))
    return last_price * base_volume


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


def _levels_from_raw(
    raw_levels: object,
    contract_size: float,
) -> list[OrderBookLevel]:
    if not isinstance(raw_levels, list):
        return []

    levels: list[OrderBookLevel] = []
    for raw_level in raw_levels:
        if not isinstance(raw_level, (list, tuple)) or len(raw_level) < 2:
            continue
        try:
            price = float(raw_level[0])
            quantity = float(raw_level[1]) * contract_size
        except (TypeError, ValueError):
            continue
        if price <= 0 or quantity <= 0:
            continue
        levels.append(OrderBookLevel(price=price, quantity=quantity))
    return levels


def _truthy(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).lower() in {"1", "true", "yes"}
