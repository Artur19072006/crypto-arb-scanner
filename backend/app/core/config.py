from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel

from app.core.fees import FALLBACK_EXCHANGE_FEES_BY_EXCHANGE
from app.domain.models import (
    AppConfig,
    DataSourceMode,
    ExchangeFees,
    ScannerFilters,
    TelegramDisplaySettings,
)


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "config.yaml"
EXAMPLE_CONFIG_PATH = PROJECT_ROOT / "config" / "config.example.yaml"

FALLBACK_FILTERS = ScannerFilters(
    min_raw_spread=0.10,
    min_net_spread=0.00,
    min_volume_24h_usd=400_000,
    exchanges=("Binance", "Bybit", "OKX", "Bitget"),
)


class Settings(BaseModel):
    app_name: str = "Crypto Perpetual Futures Arbitrage Scanner"
    config_path: Path = DEFAULT_CONFIG_PATH
    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None


@lru_cache
def get_settings() -> Settings:
    # TODO: Load .env and config.yaml values when settings persistence is added.
    return Settings()


@lru_cache
def get_app_config() -> AppConfig:
    return load_app_config()


def load_app_config(
    config_path: Path = DEFAULT_CONFIG_PATH,
    example_path: Path = EXAMPLE_CONFIG_PATH,
) -> AppConfig:
    source_path = _select_config_source(config_path, example_path)
    raw_config = _read_yaml_mapping(source_path) if source_path else {}

    fees = _load_fees(raw_config.get("fees"))
    filters = _load_filters(raw_config.get("filters"))
    telegram = _load_telegram_settings(raw_config.get("telegram"))
    data_source_mode = _load_data_source_mode(raw_config)
    supported_exchanges = _supported_exchanges(fees, filters)

    return AppConfig(
        data_source_mode=data_source_mode,
        fees=fees,
        default_filters=filters,
        supported_exchanges=supported_exchanges,
        telegram=telegram,
        config_source=str(source_path) if source_path else "built-in defaults",
    )


def _select_config_source(config_path: Path, example_path: Path) -> Path | None:
    if config_path.exists():
        return config_path
    if example_path.exists():
        return example_path
    return None


def _read_yaml_mapping(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as config_file:
        loaded = yaml.safe_load(config_file) or {}

    if not isinstance(loaded, dict):
        return {}
    return loaded


def _load_fees(raw_fees: Any) -> dict[str, ExchangeFees]:
    if not isinstance(raw_fees, dict):
        return FALLBACK_EXCHANGE_FEES_BY_EXCHANGE

    fees: dict[str, ExchangeFees] = {}
    for exchange, raw_exchange_fees in raw_fees.items():
        if not isinstance(exchange, str) or not isinstance(raw_exchange_fees, dict):
            continue
        fees[exchange] = ExchangeFees(
            maker_percent=float(raw_exchange_fees.get("maker_percent", 0.02)),
            taker_percent=float(raw_exchange_fees.get("taker_percent", 0.06)),
        )

    return fees or FALLBACK_EXCHANGE_FEES_BY_EXCHANGE


def _load_filters(raw_filters: Any) -> ScannerFilters:
    if not isinstance(raw_filters, dict):
        return FALLBACK_FILTERS

    return ScannerFilters(
        min_raw_spread=_optional_float(
            raw_filters.get(
                "min_raw_spread",
                raw_filters.get(
                    "min_raw_spread_percent",
                    FALLBACK_FILTERS.min_raw_spread,
                ),
            )
        ),
        min_net_spread=_optional_float(
            raw_filters.get(
                "min_net_spread",
                raw_filters.get(
                    "min_net_spread_percent",
                    FALLBACK_FILTERS.min_net_spread,
                ),
            )
        ),
        min_volume_24h_usd=_optional_float(
            raw_filters.get(
                "min_volume_24h_usd",
                raw_filters.get(
                    "min_24h_volume_usd",
                    FALLBACK_FILTERS.min_volume_24h_usd,
                ),
            )
        ),
        exchanges=_string_tuple(
            raw_filters.get("enabled_exchanges", FALLBACK_FILTERS.exchanges)
        ),
    )


def _load_telegram_settings(raw_telegram: Any) -> TelegramDisplaySettings:
    if not isinstance(raw_telegram, dict):
        return TelegramDisplaySettings()

    return TelegramDisplaySettings(
        enabled=bool(raw_telegram.get("enabled", False)),
        alert_cooldown_seconds=int(raw_telegram.get("alert_cooldown_seconds", 300)),
    )


def _load_data_source_mode(raw_config: dict[str, Any]) -> DataSourceMode:
    raw_mode = raw_config.get("data_source_mode")
    raw_scanner = raw_config.get("scanner")
    if raw_mode is None and isinstance(raw_scanner, dict):
        raw_mode = raw_scanner.get("data_source_mode")

    mode = str(raw_mode or "mock").lower().strip()
    if mode == "live":
        return "live"
    return "mock"


def _supported_exchanges(
    fees: dict[str, ExchangeFees],
    filters: ScannerFilters,
) -> tuple[str, ...]:
    configured = list(fees.keys())
    for exchange in filters.exchanges:
        if exchange not in configured:
            configured.append(exchange)
    return tuple(configured)


def _optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


def _string_tuple(value: Any) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(str(item) for item in value if str(item).strip())
