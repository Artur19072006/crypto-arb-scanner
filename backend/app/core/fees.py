from app.domain.models import ExchangeFees


FALLBACK_EXCHANGE_FEES_BY_EXCHANGE: dict[str, ExchangeFees] = {
    "Binance": ExchangeFees(maker_percent=0.02, taker_percent=0.05),
    "Bybit": ExchangeFees(maker_percent=0.02, taker_percent=0.055),
    "OKX": ExchangeFees(maker_percent=0.02, taker_percent=0.05),
    "Bitget": ExchangeFees(maker_percent=0.02, taker_percent=0.06),
    "Gate": ExchangeFees(maker_percent=0.02, taker_percent=0.05),
    "KuCoin": ExchangeFees(maker_percent=0.02, taker_percent=0.06),
}

FALLBACK_EXCHANGE_FEES = ExchangeFees(maker_percent=0.02, taker_percent=0.06)
