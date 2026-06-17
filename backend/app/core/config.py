from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel

from app.core.fees import FALLBACK_EXCHANGE_FEES_BY_EXCHANGE
from app.domain.models import (
    AlertConfig,
    AppConfig,
    DataSourceMode,
    DepthCheckConfig,
    ExchangeFees,
    ScannerFilters,
    SymbolSelectionConfig,
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
FALLBACK_SYMBOL_ALLOWLIST = ("BTCUSDT", "ETHUSDT", "SOLUSDT")


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
    enabled_connectors = _load_enabled_connectors(raw_config, data_source_mode)
    max_symbols = _load_max_symbols(raw_config)
    symbol_allowlist = _load_symbol_allowlist(raw_config)
    symbol_selection = _load_symbol_selection(
        raw_config,
        max_symbols=max_symbols,
        default_min_volume_24h_usd=filters.min_volume_24h_usd,
    )
    depth_check = _load_depth_check(raw_config.get("depth_check"))
    alerts = _load_alerts(raw_config.get("alerts"))
    supported_exchanges = _supported_exchanges(fees, filters)

    return AppConfig(
        data_source_mode=data_source_mode,
        enabled_connectors=enabled_connectors,
        max_symbols=max_symbols,
        symbol_allowlist=symbol_allowlist,
        symbol_selection=symbol_selection,
        fees=fees,
        default_filters=filters,
        supported_exchanges=supported_exchanges,
        depth_check=depth_check,
        alerts=alerts,
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
    defaults = TelegramDisplaySettings()
    if not isinstance(raw_telegram, dict):
        return defaults

    return TelegramDisplaySettings(
        enabled=bool(raw_telegram.get("enabled", False)),
        bot_token_env=str(raw_telegram.get("bot_token_env", defaults.bot_token_env)),
        chat_id_env=str(raw_telegram.get("chat_id_env", defaults.chat_id_env)),
        parse_mode=_telegram_parse_mode(
            raw_telegram.get("parse_mode", defaults.parse_mode)
        ),
        timeout_seconds=max(
            1,
            int(raw_telegram.get("timeout_seconds", defaults.timeout_seconds)),
        ),
    )


def _load_depth_check(raw_depth_check: Any) -> DepthCheckConfig:
    defaults = DepthCheckConfig()
    if not isinstance(raw_depth_check, dict):
        return defaults

    return DepthCheckConfig(
        enabled=bool(raw_depth_check.get("enabled", False)),
        target_notional_usd=float(
            raw_depth_check.get(
                "target_notional_usd",
                defaults.target_notional_usd,
            )
        ),
        max_opportunities_to_check=max(
            1,
            int(
                raw_depth_check.get(
                    "max_opportunities_to_check",
                    defaults.max_opportunities_to_check,
                )
            ),
        ),
        order_book_limit=max(
            1,
            int(
                raw_depth_check.get(
                    "order_book_limit",
                    defaults.order_book_limit,
                )
            ),
        ),
        max_allowed_slippage_percent=max(
            0.0,
            float(
                raw_depth_check.get(
                    "max_allowed_slippage_percent",
                    defaults.max_allowed_slippage_percent,
                )
            ),
        ),
    )


def _load_alerts(raw_alerts: Any) -> AlertConfig:
    defaults = AlertConfig()
    if not isinstance(raw_alerts, dict):
        return defaults

    return AlertConfig(
        enabled=bool(raw_alerts.get("enabled", False)),
        min_net_spread_percent=float(
            raw_alerts.get(
                "min_net_spread_percent",
                defaults.min_net_spread_percent,
            )
        ),
        min_depth_adjusted_net_spread_percent=float(
            raw_alerts.get(
                "min_depth_adjusted_net_spread_percent",
                defaults.min_depth_adjusted_net_spread_percent,
            )
        ),
        require_depth_status=_depth_status_tuple(
            raw_alerts.get(
                "require_depth_status",
                defaults.require_depth_status,
            )
        ),
        max_allowed_slippage_percent=max(
            0.0,
            float(
                raw_alerts.get(
                    "max_allowed_slippage_percent",
                    defaults.max_allowed_slippage_percent,
                )
            ),
        ),
        min_volume_24h_usd=max(
            0.0,
            float(raw_alerts.get("min_volume_24h_usd", defaults.min_volume_24h_usd)),
        ),
        cooldown_seconds=max(
            0,
            int(raw_alerts.get("cooldown_seconds", defaults.cooldown_seconds)),
        ),
        max_alerts_per_scan=max(
            1,
            int(raw_alerts.get("max_alerts_per_scan", defaults.max_alerts_per_scan)),
        ),
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


def _load_enabled_connectors(
    raw_config: dict[str, Any],
    data_source_mode: DataSourceMode,
) -> tuple[str, ...]:
    raw_value = raw_config.get("enabled_connectors")
    if raw_value is None:
        raw_scanner = raw_config.get("scanner")
        if isinstance(raw_scanner, dict):
            raw_value = raw_scanner.get("enabled_connectors")

    if isinstance(raw_value, (list, tuple)):
        connectors = tuple(
            str(connector).lower().strip()
            for connector in raw_value
            if str(connector).strip()
        )
        if connectors:
            return connectors

    return ("fake",) if data_source_mode == "mock" else ("binance", "bybit")


def _load_max_symbols(raw_config: dict[str, Any]) -> int:
    raw_value = raw_config.get("max_symbols")
    if raw_value is None:
        raw_scanner = raw_config.get("scanner")
        if isinstance(raw_scanner, dict):
            raw_value = raw_scanner.get("max_symbols")

    return max(1, int(raw_value or 10))


def _load_symbol_allowlist(raw_config: dict[str, Any]) -> tuple[str, ...]:
    raw_value = raw_config.get("symbol_allowlist")
    if raw_value is None:
        raw_scanner = raw_config.get("scanner")
        if isinstance(raw_scanner, dict):
            raw_value = raw_scanner.get("symbol_allowlist")

    symbols = _string_tuple(raw_value)
    return symbols or FALLBACK_SYMBOL_ALLOWLIST


def _load_symbol_selection(
    raw_config: dict[str, Any],
    max_symbols: int,
    default_min_volume_24h_usd: float | None,
) -> SymbolSelectionConfig:
    raw_value = raw_config.get("symbol_selection")
    if raw_value is None:
        raw_scanner = raw_config.get("scanner")
        if isinstance(raw_scanner, dict):
            raw_value = raw_scanner.get("symbol_selection")

    if not isinstance(raw_value, dict):
        return SymbolSelectionConfig(
            mode="manual",
            min_volume_24h_usd=default_min_volume_24h_usd,
            max_symbols=max_symbols,
        )

    mode = str(raw_value.get("mode", "manual")).lower().strip()
    if mode != "auto":
        mode = "manual"

    raw_max_symbols = raw_value.get("max_symbols", max_symbols)
    raw_min_exchanges_required = raw_value.get("min_exchanges_required", 2)
    return SymbolSelectionConfig(
        mode=mode,
        min_volume_24h_usd=_optional_float(
            raw_value.get("min_volume_24h_usd", default_min_volume_24h_usd)
        ),
        max_volume_24h_usd=_optional_float(raw_value.get("max_volume_24h_usd")),
        max_symbols=max(1, int(raw_max_symbols or max_symbols)),
        min_exchanges_required=max(2, int(raw_min_exchanges_required or 2)),
        include_symbols=_string_tuple(raw_value.get("include_symbols")),
        exclude_symbols=_string_tuple(raw_value.get("exclude_symbols")),
    )


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


def _depth_status_tuple(value: Any) -> tuple[str, ...]:
    allowed_statuses = {"OK", "Thin", "Insufficient", "Unknown"}
    statuses = _string_tuple(value)
    parsed = tuple(status for status in statuses if status in allowed_statuses)
    return parsed or AlertConfig().require_depth_status


def _telegram_parse_mode(value: Any) -> str:
    parse_mode = str(value or "HTML")
    if parse_mode in {"HTML", "Markdown", "MarkdownV2"}:
        return parse_mode
    return "HTML"
