import asyncio
import json
from datetime import datetime, timezone
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from app.connectors.base import ExchangeConnector
from app.domain.models import MarketSnapshot, MarketSymbol
from app.services.symbols import normalize_symbol


GATE_SETTLE = "usdt"


class GatePublicConnector(ExchangeConnector):
    name = "gate"
    exchange_name = "Gate"
    data_source = "gate_public_rest"

    def __init__(
        self,
        symbol_allowlist: tuple[str, ...],
        max_symbols: int,
        base_url: str = "https://api.gateio.ws/api/v4",
        timeout_seconds: int = 10,
    ) -> None:
        self.symbol_allowlist = tuple(
            normalize_symbol(symbol, "Gate")
            for symbol in symbol_allowlist
            if normalize_symbol(symbol, "Gate")
        )
        self.max_symbols = max_symbols
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    async def fetch_snapshots(
        self,
        symbols: tuple[str, ...] | None = None,
    ) -> list[MarketSnapshot]:
        selected_symbols = (
            _normalize_symbol_tuple(symbols, "Gate")
            if symbols is not None
            else tuple(await self.fetch_symbols())
        )
        if not selected_symbols:
            return []

        contracts_response = await self._get_json(f"/futures/{GATE_SETTLE}/contracts")
        contracts_by_symbol = self._contract_map(contracts_response)
        selected_contracts = {
            symbol: contracts_by_symbol[symbol]
            for symbol in selected_symbols
            if symbol in contracts_by_symbol
        }
        if not selected_contracts:
            return []

        tickers_response = await self._get_json(f"/futures/{GATE_SETTLE}/tickers")
        tickers_by_contract = self._ticker_map(tickers_response)

        snapshots: list[MarketSnapshot] = []
        for symbol, contract in selected_contracts.items():
            contract_name = _contract_name_from_contract(contract)
            ticker = tickers_by_contract.get(contract_name)
            if ticker is None:
                continue
            try:
                snapshots.append(
                    self._snapshot_from_ticker(
                        symbol=symbol,
                        ticker=ticker,
                        contract=contract,
                    )
                )
            except (KeyError, TypeError, ValueError):
                continue

        if selected_contracts and not snapshots:
            raise RuntimeError("No Gate snapshots could be parsed")

        return snapshots

    async def fetch_symbols(self) -> list[str]:
        contracts_response = await self._get_json(f"/futures/{GATE_SETTLE}/contracts")
        return self._symbols_from_contracts(
            contracts_response,
            allowlist=set(self.symbol_allowlist),
            max_symbols=self.max_symbols,
        )

    async def fetch_symbol_markets(self) -> list[MarketSymbol]:
        contracts_response = await self._get_json(f"/futures/{GATE_SETTLE}/contracts")
        symbols = self._symbols_from_contracts(contracts_response)
        tickers_response = await self._get_json(f"/futures/{GATE_SETTLE}/tickers")
        tickers = self._ticker_map(tickers_response)

        markets: list[MarketSymbol] = []
        for contract in self._data_list(contracts_response):
            contract_name = _contract_name_from_contract(contract)
            if not contract_name:
                continue
            symbol = normalize_symbol(contract_name, "Gate")
            if symbol not in symbols:
                continue
            markets.append(
                MarketSymbol(
                    exchange="Gate",
                    symbol=symbol,
                    volume_24h_usd=_ticker_volume_24h_usd(tickers.get(contract_name, {})),
                )
            )

        return markets

    def _symbols_from_contracts(
        self,
        response: dict | list,
        allowlist: set[str] | None = None,
        max_symbols: int | None = None,
    ) -> list[str]:
        allowed_symbols = allowlist or set()
        symbols: list[str] = []
        for contract in self._data_list(response):
            contract_name = _contract_name_from_contract(contract)
            if not contract_name:
                continue
            symbol = normalize_symbol(contract_name, "Gate")
            if allowed_symbols and symbol not in allowed_symbols:
                continue

            symbols.append(symbol)
            if max_symbols is not None and len(symbols) >= max_symbols:
                break

        return symbols

    def _contract_map(self, response: dict | list) -> dict[str, dict]:
        contracts: dict[str, dict] = {}
        for contract in self._data_list(response):
            contract_name = _contract_name_from_contract(contract)
            if not contract_name:
                continue
            contracts[normalize_symbol(contract_name, "Gate")] = contract
        return contracts

    def _ticker_map(self, response: dict | list) -> dict[str, dict]:
        tickers: dict[str, dict] = {}
        for ticker in self._data_list(response):
            contract_name = _gate_contract_name(str(ticker.get("contract", "")))
            if contract_name:
                tickers[contract_name] = ticker
        return tickers

    def _snapshot_from_ticker(
        self,
        symbol: str,
        ticker: dict,
        contract: dict,
    ) -> MarketSnapshot:
        best_bid = float(ticker["highest_bid"])
        best_ask = float(ticker["lowest_ask"])
        if best_bid <= 0 or best_ask <= 0:
            raise ValueError("Bid/ask must be positive")

        return MarketSnapshot(
            exchange="Gate",
            symbol=normalize_symbol(symbol, "Gate"),
            best_bid=best_bid,
            best_bid_size=_float_or_zero(
                _first_present(
                    ticker.get("highest_bid_size"),
                    ticker.get("bid_size"),
                    ticker.get("bidSize"),
                )
            ),
            best_ask=best_ask,
            best_ask_size=_float_or_zero(
                _first_present(
                    ticker.get("lowest_ask_size"),
                    ticker.get("ask_size"),
                    ticker.get("askSize"),
                )
            ),
            volume_24h_usd=_ticker_volume_24h_usd(ticker),
            funding_rate_percent=_float_or_zero(
                _first_present(
                    ticker.get("funding_rate"),
                    ticker.get("funding_rate_indicative"),
                    contract.get("funding_rate"),
                )
            )
            * 100,
            next_funding_time=_datetime_from_seconds(
                _first_present(
                    contract.get("funding_next_apply"),
                    contract.get("funding_time"),
                    ticker.get("funding_time"),
                )
            ),
            timestamp=datetime.now(timezone.utc),
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
        data: object = response.get("data", response) if isinstance(response, dict) else response
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
        if isinstance(data, dict):
            return [data]
        raise ValueError("Gate response data must be a list or object")

    # TODO: Add Gate public order book depth support separately if depth checks need it.
    # REST-only connector. No auth, private account APIs, or trading APIs here.


def _contract_name_from_contract(contract: dict) -> str:
    contract_name = _gate_contract_name(str(contract.get("name", "")))
    if not contract_name:
        return ""
    if _truthy(contract.get("in_delisting")):
        return ""

    contract_type = str(contract.get("type", "direct") or "direct").lower()
    if contract_type != "direct":
        return ""
    return contract_name


def _gate_contract_name(value: str) -> str:
    contract_name = value.upper().strip()
    parts = contract_name.split("_")
    if len(parts) != 2 or parts[1] != "USDT" or not parts[0]:
        return ""
    return contract_name


def _gate_contract(symbol: str) -> str:
    normalized_symbol = normalize_symbol(symbol, "Gate")
    if not normalized_symbol.endswith("USDT") or len(normalized_symbol) <= 4:
        return ""
    return f"{normalized_symbol[:-4]}_USDT"


def _ticker_volume_24h_usd(ticker: dict) -> float:
    quote_volume = _float_or_zero(
        _first_present(
            ticker.get("volume_24h_quote"),
            ticker.get("volume_24h_usd"),
            ticker.get("volume_24h_settle"),
        )
    )
    if quote_volume > 0:
        return quote_volume

    last_price = _float_or_zero(_first_present(ticker.get("last"), ticker.get("mark_price")))
    base_volume = _float_or_zero(
        _first_present(
            ticker.get("volume_24h_base"),
            ticker.get("volume_24h"),
            ticker.get("volume"),
        )
    )
    return last_price * base_volume


def _datetime_from_seconds(value: object) -> datetime | None:
    if value in (None, "", 0, "0"):
        return None

    timestamp = float(value)
    if timestamp > 10_000_000_000:
        timestamp /= 1000
    return datetime.fromtimestamp(timestamp, tz=timezone.utc)


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


def _truthy(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).lower() in {"1", "true", "yes"}
