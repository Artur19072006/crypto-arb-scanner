from typing import Literal


ExchangeName = Literal["Binance", "Bybit", "OKX", "Bitget", "Gate", "KuCoin"]

SUPPORTED_NORMALIZED_SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT")


def normalize_symbol(symbol: str, exchange: str | None = None) -> str:
    normalized = symbol.upper().strip()
    normalized = normalized.replace("-USDT-SWAP", "USDT")
    normalized = normalized.replace("_", "")
    normalized = normalized.replace("-", "")

    return normalized


def is_supported_normalized_symbol(symbol: str) -> bool:
    return normalize_symbol(symbol) in SUPPORTED_NORMALIZED_SYMBOLS


def symbol_format_examples() -> dict[str, str]:
    return {
        "normalized": "BTCUSDT",
        "Binance": "BTCUSDT",
        "Bybit": "BTCUSDT",
        "OKX": "BTC-USDT-SWAP",
        "Gate": "BTC_USDT",
    }


# Future connector examples:
# Binance USDT perpetual: BTCUSDT
# Bybit USDT perpetual: BTCUSDT
# OKX USDT perpetual swap: BTC-USDT-SWAP
# Gate USDT perpetual: BTC_USDT
