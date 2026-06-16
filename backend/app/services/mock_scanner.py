from collections import defaultdict
from datetime import datetime, timezone

from app.connectors.base import MarketSnapshot
from app.connectors.fake import FakeExchangeConnector
from app.models.opportunity import Opportunity


DEFAULT_TAKER_FEE_PERCENT = {
    "Binance": 0.05,
    "Bybit": 0.055,
    "OKX": 0.05,
    "Bitget": 0.06,
    "Gate": 0.05,
    "KuCoin": 0.06,
}


async def get_mock_opportunities() -> list[Opportunity]:
    snapshots = await FakeExchangeConnector().get_snapshots()
    opportunities = _build_opportunities_from_snapshots(snapshots)
    return sorted(
        opportunities,
        key=lambda opportunity: opportunity.estimated_net_spread_percent,
        reverse=True,
    )


def _build_opportunities_from_snapshots(
    snapshots: list[MarketSnapshot],
) -> list[Opportunity]:
    by_symbol: dict[str, list[MarketSnapshot]] = defaultdict(list)
    for snapshot in snapshots:
        by_symbol[snapshot.symbol].append(snapshot)

    opportunities: list[Opportunity] = []
    for symbol, symbol_snapshots in by_symbol.items():
        if len(symbol_snapshots) < 2:
            continue

        lowest_ask = min(symbol_snapshots, key=lambda item: item.best_ask)
        highest_bid = max(symbol_snapshots, key=lambda item: item.best_bid)
        if lowest_ask.exchange == highest_bid.exchange:
            continue

        # Trading-specific logic: use executable bid/ask data, never last traded price.
        raw_spread_percent = (
            (highest_bid.best_bid - lowest_ask.best_ask) / lowest_ask.best_ask * 100
        )
        estimated_net_spread_percent = raw_spread_percent - _round_trip_taker_fees(
            lowest_ask.exchange,
            highest_bid.exchange,
        )

        opportunities.append(
            Opportunity(
                symbol=symbol,
                long_exchange=lowest_ask.exchange,
                short_exchange=highest_bid.exchange,
                ask_price=lowest_ask.best_ask,
                bid_price=highest_bid.best_bid,
                raw_spread_percent=round(raw_spread_percent, 4),
                estimated_net_spread_percent=round(estimated_net_spread_percent, 4),
                volume_24h_usd=min(
                    lowest_ask.volume_24h_usd,
                    highest_bid.volume_24h_usd,
                ),
                best_ask_size=lowest_ask.best_ask_size,
                best_bid_size=highest_bid.best_bid_size,
                long_funding_rate_percent=lowest_ask.funding_rate_percent,
                short_funding_rate_percent=highest_bid.funding_rate_percent,
                funding_rate_difference_percent=round(
                    highest_bid.funding_rate_percent - lowest_ask.funding_rate_percent,
                    4,
                ),
                next_funding_time=lowest_ask.next_funding_time,
                funding_impact=_funding_impact(
                    lowest_ask.funding_rate_percent,
                    highest_bid.funding_rate_percent,
                ),
                liquidity_status=_liquidity_status(
                    lowest_ask.volume_24h_usd,
                    highest_bid.volume_24h_usd,
                    lowest_ask.best_ask_size,
                    highest_bid.best_bid_size,
                ),
                timestamp=datetime.now(timezone.utc),
            )
        )

    return opportunities


def _round_trip_taker_fees(long_exchange: str, short_exchange: str) -> float:
    long_fee = DEFAULT_TAKER_FEE_PERCENT.get(long_exchange, 0.06)
    short_fee = DEFAULT_TAKER_FEE_PERCENT.get(short_exchange, 0.06)
    return (long_fee * 2) + (short_fee * 2)


def _funding_impact(long_rate: float, short_rate: float) -> str:
    difference = short_rate - long_rate
    if difference >= 0.005:
        return "Good"
    if difference <= -0.005:
        return "Bad"
    return "Neutral"


def _liquidity_status(
    long_volume: float,
    short_volume: float,
    ask_size: float,
    bid_size: float,
) -> str:
    reference_volume = min(long_volume, short_volume)
    reference_size = min(ask_size, bid_size)
    if reference_volume >= 400_000 and reference_size > 0:
        return "OK"
    if reference_volume >= 100_000:
        return "Thin"
    return "Holey"
