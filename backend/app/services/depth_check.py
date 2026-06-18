import asyncio
from dataclasses import dataclass
from typing import Literal

from app.connectors.base import ExchangeConnector
from app.domain.models import (
    ArbitrageOpportunity,
    DepthCheckConfig,
    DepthCheckResult,
    DepthStatus,
    OrderBookLevel,
    OrderBookSnapshot,
)


FillSide = Literal["buy", "sell"]


@dataclass(frozen=True)
class NotionalFillResult:
    can_fill: bool
    effective_price: float | None
    slippage_percent: float | None
    filled_notional_usd: float


CONNECTOR_EXCHANGE_NAMES = {
    "binance": "Binance",
    "bybit": "Bybit",
    "okx": "OKX",
    "bitget": "Bitget",
    "gate": "Gate",
    "mexc": "MEXC",
}


async def apply_depth_checks(
    opportunities: list[ArbitrageOpportunity],
    connectors: list[ExchangeConnector],
    depth_config: DepthCheckConfig,
) -> list[ArbitrageOpportunity]:
    if not depth_config.enabled or not opportunities:
        return opportunities

    connector_by_exchange = _connectors_by_exchange(connectors)
    checked_limit = min(depth_config.max_opportunities_to_check, len(opportunities))
    checked_opportunities: list[ArbitrageOpportunity] = []
    for index, opportunity in enumerate(opportunities):
        if index >= checked_limit:
            checked_opportunities.append(opportunity)
            continue

        depth_result = await check_opportunity_depth(
            opportunity=opportunity,
            connector_by_exchange=connector_by_exchange,
            depth_config=depth_config,
        )
        checked_opportunities.append(
            opportunity.model_copy(update={"depth_check": depth_result})
        )

    return checked_opportunities


async def check_opportunity_depth(
    opportunity: ArbitrageOpportunity,
    connector_by_exchange: dict[str, ExchangeConnector],
    depth_config: DepthCheckConfig,
) -> DepthCheckResult:
    long_connector = connector_by_exchange.get(opportunity.long_exchange)
    short_connector = connector_by_exchange.get(opportunity.short_exchange)
    missing_reasons = []
    if long_connector is None:
        missing_reasons.append(
            f"No public REST order book connector for {opportunity.long_exchange}"
        )
    if short_connector is None:
        missing_reasons.append(
            f"No public REST order book connector for {opportunity.short_exchange}"
        )
    if missing_reasons:
        return _unknown_result(depth_config, missing_reasons)

    long_result, short_result = await asyncio.gather(
        long_connector.fetch_order_book(
            opportunity.symbol,
            limit=depth_config.order_book_limit,
        ),
        short_connector.fetch_order_book(
            opportunity.symbol,
            limit=depth_config.order_book_limit,
        ),
        return_exceptions=True,
    )

    failure_reasons = []
    if isinstance(long_result, Exception):
        failure_reasons.append(
            f"{opportunity.long_exchange} depth request failed: {long_result}"
        )
    if isinstance(short_result, Exception):
        failure_reasons.append(
            f"{opportunity.short_exchange} depth request failed: {short_result}"
        )
    if failure_reasons:
        return _unknown_result(depth_config, failure_reasons)

    return calculate_depth_result(
        opportunity=opportunity,
        long_order_book=long_result,
        short_order_book=short_result,
        depth_config=depth_config,
    )


def calculate_depth_result(
    opportunity: ArbitrageOpportunity,
    long_order_book: OrderBookSnapshot,
    short_order_book: OrderBookSnapshot,
    depth_config: DepthCheckConfig,
) -> DepthCheckResult:
    long_fill = simulate_notional_fill(
        long_order_book.asks,
        target_notional_usd=depth_config.target_notional_usd,
        side="buy",
    )
    short_fill = simulate_notional_fill(
        short_order_book.bids,
        target_notional_usd=depth_config.target_notional_usd,
        side="sell",
    )

    depth_status: DepthStatus = "OK"
    reasons: list[str] = []
    if not long_fill.can_fill:
        reasons.append(
            f"Long side has insufficient ask depth for ${depth_config.target_notional_usd:,.2f}"
        )
    if not short_fill.can_fill:
        reasons.append(
            f"Short side has insufficient bid depth for ${depth_config.target_notional_usd:,.2f}"
        )
    if reasons:
        depth_status = "Insufficient"

    adjusted_raw_spread = None
    adjusted_net_spread = None
    if long_fill.effective_price is not None and short_fill.effective_price is not None:
        adjusted_raw_spread = (
            (short_fill.effective_price - long_fill.effective_price)
            / long_fill.effective_price
            * 100
        )
        adjusted_net_spread = adjusted_raw_spread - opportunity.estimated_fee_percent

    if depth_status == "OK":
        if (
            long_fill.slippage_percent is not None
            and long_fill.slippage_percent
            > depth_config.max_allowed_slippage_percent
        ):
            depth_status = "Thin"
            reasons.append(
                "Long slippage exceeds "
                f"{depth_config.max_allowed_slippage_percent:.4f}%"
            )
        if (
            short_fill.slippage_percent is not None
            and short_fill.slippage_percent
            > depth_config.max_allowed_slippage_percent
        ):
            depth_status = "Thin"
            reasons.append(
                "Short slippage exceeds "
                f"{depth_config.max_allowed_slippage_percent:.4f}%"
            )

    if depth_status == "OK":
        reasons.append("Target notional fills on both sides within slippage limit")

    return DepthCheckResult(
        target_notional_usd=depth_config.target_notional_usd,
        can_fill_long=long_fill.can_fill,
        can_fill_short=short_fill.can_fill,
        long_effective_price=_round_optional(long_fill.effective_price),
        short_effective_price=_round_optional(short_fill.effective_price),
        long_slippage_percent=_round_optional(long_fill.slippage_percent),
        short_slippage_percent=_round_optional(short_fill.slippage_percent),
        depth_adjusted_raw_spread_percent=_round_optional(adjusted_raw_spread),
        depth_adjusted_net_spread_percent=_round_optional(adjusted_net_spread),
        depth_status=depth_status,
        depth_reasons=reasons,
    )


def simulate_notional_fill(
    levels: list[OrderBookLevel],
    target_notional_usd: float,
    side: FillSide,
) -> NotionalFillResult:
    sorted_levels = _sorted_levels(levels, side)
    if not sorted_levels:
        return NotionalFillResult(
            can_fill=False,
            effective_price=None,
            slippage_percent=None,
            filled_notional_usd=0.0,
        )

    remaining_notional = target_notional_usd
    filled_notional = 0.0
    filled_quantity = 0.0
    for level in sorted_levels:
        available_notional = level.price * level.quantity
        if available_notional <= 0:
            continue

        consumed_notional = min(available_notional, remaining_notional)
        filled_notional += consumed_notional
        filled_quantity += consumed_notional / level.price
        remaining_notional -= consumed_notional
        if remaining_notional <= 1e-9:
            break

    if remaining_notional > 1e-9 or filled_quantity <= 0:
        return NotionalFillResult(
            can_fill=False,
            effective_price=None,
            slippage_percent=None,
            filled_notional_usd=filled_notional,
        )

    effective_price = filled_notional / filled_quantity
    top_price = sorted_levels[0].price
    if side == "buy":
        slippage_percent = (effective_price - top_price) / top_price * 100
    else:
        slippage_percent = (top_price - effective_price) / top_price * 100

    return NotionalFillResult(
        can_fill=True,
        effective_price=effective_price,
        slippage_percent=max(slippage_percent, 0.0),
        filled_notional_usd=filled_notional,
    )


def _connectors_by_exchange(
    connectors: list[ExchangeConnector],
) -> dict[str, ExchangeConnector]:
    result: dict[str, ExchangeConnector] = {}
    for connector in connectors:
        exchange_name = getattr(
            connector,
            "exchange_name",
            CONNECTOR_EXCHANGE_NAMES.get(connector.name, ""),
        )
        if exchange_name:
            result[exchange_name] = connector
    return result


def _unknown_result(
    depth_config: DepthCheckConfig,
    reasons: list[str],
) -> DepthCheckResult:
    return DepthCheckResult(
        target_notional_usd=depth_config.target_notional_usd,
        can_fill_long=False,
        can_fill_short=False,
        long_effective_price=None,
        short_effective_price=None,
        long_slippage_percent=None,
        short_slippage_percent=None,
        depth_adjusted_raw_spread_percent=None,
        depth_adjusted_net_spread_percent=None,
        depth_status="Unknown",
        depth_reasons=reasons,
    )


def _sorted_levels(
    levels: list[OrderBookLevel],
    side: FillSide,
) -> list[OrderBookLevel]:
    return sorted(
        (level for level in levels if level.price > 0 and level.quantity > 0),
        key=lambda level: level.price,
        reverse=side == "sell",
    )


def _round_optional(value: float | None) -> float | None:
    if value is None:
        return None
    return round(value, 4)
