from collections import defaultdict
from datetime import datetime, timezone

from app.core.fees import FALLBACK_EXCHANGE_FEES
from app.domain.models import (
    ArbitrageOpportunity,
    ExchangeFees,
    FundingImpact,
    LiquidityStatus,
    MarketSnapshot,
    ScannerFilters,
)
from app.services.symbols import exchange_name_key


def calculate_opportunities(
    snapshots: list[MarketSnapshot],
    fees_by_exchange: dict[str, ExchangeFees],
    filters: ScannerFilters | None = None,
) -> list[ArbitrageOpportunity]:
    active_filters = filters or ScannerFilters()
    filtered_snapshots = _apply_snapshot_filters(snapshots, active_filters)
    opportunities = _calculate_unfiltered_opportunities(
        filtered_snapshots,
        fees_by_exchange,
    )
    filtered = _apply_opportunity_filters(opportunities, active_filters)
    return sorted(
        filtered,
        key=lambda opportunity: opportunity.estimated_net_spread_percent,
        reverse=True,
    )


def _apply_snapshot_filters(
    snapshots: list[MarketSnapshot],
    filters: ScannerFilters,
) -> list[MarketSnapshot]:
    if not filters.exchanges:
        return snapshots

    allowed_exchanges = {exchange_name_key(exchange) for exchange in filters.exchanges}
    return [
        snapshot
        for snapshot in snapshots
        if exchange_name_key(snapshot.exchange) in allowed_exchanges
    ]


def _calculate_unfiltered_opportunities(
    snapshots: list[MarketSnapshot],
    fees_by_exchange: dict[str, ExchangeFees],
) -> list[ArbitrageOpportunity]:
    by_symbol: dict[str, list[MarketSnapshot]] = defaultdict(list)
    for snapshot in snapshots:
        by_symbol[snapshot.symbol].append(snapshot)

    opportunities: list[ArbitrageOpportunity] = []
    for symbol_snapshots in by_symbol.values():
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
        estimated_fee_percent = _round_trip_taker_fees(
            lowest_ask.exchange,
            highest_bid.exchange,
            fees_by_exchange,
        )
        estimated_net_spread_percent = raw_spread_percent - estimated_fee_percent

        opportunities.append(
            ArbitrageOpportunity(
                symbol=lowest_ask.symbol,
                long_exchange=lowest_ask.exchange,
                short_exchange=highest_bid.exchange,
                ask_price=lowest_ask.best_ask,
                bid_price=highest_bid.best_bid,
                raw_spread_percent=round(raw_spread_percent, 4),
                estimated_net_spread_percent=round(estimated_net_spread_percent, 4),
                estimated_fee_percent=round(estimated_fee_percent, 4),
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


def _round_trip_taker_fees(
    long_exchange: str,
    short_exchange: str,
    fees_by_exchange: dict[str, ExchangeFees],
) -> float:
    long_fee = _exchange_fees(long_exchange, fees_by_exchange)
    short_fee = _exchange_fees(short_exchange, fees_by_exchange)
    return (long_fee.taker_percent * 2) + (short_fee.taker_percent * 2)


def _exchange_fees(
    exchange: str,
    fees_by_exchange: dict[str, ExchangeFees],
) -> ExchangeFees:
    fee = fees_by_exchange.get(exchange)
    if fee is not None:
        return fee

    exchange_key = exchange_name_key(exchange)
    for configured_exchange, configured_fee in fees_by_exchange.items():
        if exchange_name_key(configured_exchange) == exchange_key:
            return configured_fee

    return FALLBACK_EXCHANGE_FEES


def _apply_opportunity_filters(
    opportunities: list[ArbitrageOpportunity],
    filters: ScannerFilters,
) -> list[ArbitrageOpportunity]:
    return filter_opportunities(opportunities, filters)


def filter_opportunities(
    opportunities: list[ArbitrageOpportunity],
    filters: ScannerFilters,
) -> list[ArbitrageOpportunity]:
    allowed_exchanges = {exchange_name_key(exchange) for exchange in filters.exchanges}
    filtered: list[ArbitrageOpportunity] = []
    for opportunity in opportunities:
        if (
            filters.min_raw_spread is not None
            and opportunity.raw_spread_percent < filters.min_raw_spread
        ):
            continue
        if (
            filters.min_net_spread is not None
            and opportunity.estimated_net_spread_percent < filters.min_net_spread
        ):
            continue
        if (
            filters.min_volume_24h_usd is not None
            and opportunity.volume_24h_usd < filters.min_volume_24h_usd
        ):
            continue
        if allowed_exchanges and (
            exchange_name_key(opportunity.long_exchange) not in allowed_exchanges
            or exchange_name_key(opportunity.short_exchange) not in allowed_exchanges
        ):
            continue

        filtered.append(opportunity)

    return filtered


def _funding_impact(long_rate: float, short_rate: float) -> FundingImpact:
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
) -> LiquidityStatus:
    reference_volume = min(long_volume, short_volume)
    reference_size = min(ask_size, bid_size)
    if reference_volume >= 400_000 and reference_size > 0:
        return "OK"
    if reference_volume >= 100_000:
        return "Thin"
    return "Holey"
