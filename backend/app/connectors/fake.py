from datetime import datetime, timedelta, timezone

from app.connectors.base import ExchangeConnector
from app.domain.models import MarketSnapshot


class FakeExchangeConnector(ExchangeConnector):
    name = "fake"

    async def get_snapshots(self) -> list[MarketSnapshot]:
        now = datetime.now(timezone.utc)
        next_funding = now + timedelta(hours=4)

        # TODO: Replace this with Binance USDT perpetual futures connector first.
        # TODO: Add Bybit after Binance, then OKX, Bitget, Gate, and KuCoin one by one.
        return [
            MarketSnapshot(
                exchange="Binance",
                symbol="BTCUSDT",
                best_bid=65020.20,
                best_bid_size=0.72,
                best_ask=65021.10,
                best_ask_size=0.61,
                volume_24h_usd=1_250_000_000,
                funding_rate_percent=0.0100,
                next_funding_time=next_funding,
                timestamp=now,
            ),
            MarketSnapshot(
                exchange="Bybit",
                symbol="BTCUSDT",
                best_bid=65105.50,
                best_bid_size=0.44,
                best_ask=65106.40,
                best_ask_size=0.38,
                volume_24h_usd=920_000_000,
                funding_rate_percent=0.0125,
                next_funding_time=next_funding,
                timestamp=now,
            ),
            MarketSnapshot(
                exchange="Binance",
                symbol="ETHUSDT",
                best_bid=3515.20,
                best_bid_size=8.4,
                best_ask=3515.70,
                best_ask_size=6.9,
                volume_24h_usd=720_000_000,
                funding_rate_percent=0.0080,
                next_funding_time=next_funding,
                timestamp=now,
            ),
            MarketSnapshot(
                exchange="Bybit",
                symbol="ETHUSDT",
                best_bid=3523.40,
                best_bid_size=4.6,
                best_ask=3524.10,
                best_ask_size=5.1,
                volume_24h_usd=540_000_000,
                funding_rate_percent=0.0060,
                next_funding_time=next_funding,
                timestamp=now,
            ),
            MarketSnapshot(
                exchange="OKX",
                symbol="SOLUSDT",
                best_bid=142.15,
                best_bid_size=920.0,
                best_ask=142.18,
                best_ask_size=740.0,
                volume_24h_usd=118_000_000,
                funding_rate_percent=-0.0030,
                next_funding_time=next_funding,
                timestamp=now,
            ),
            MarketSnapshot(
                exchange="Bitget",
                symbol="SOLUSDT",
                best_bid=142.62,
                best_bid_size=510.0,
                best_ask=142.66,
                best_ask_size=455.0,
                volume_24h_usd=86_000_000,
                funding_rate_percent=0.0040,
                next_funding_time=next_funding,
                timestamp=now,
            ),
        ]
