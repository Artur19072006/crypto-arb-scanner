import unittest
from datetime import datetime, timezone

from app.domain.models import (
    ArbitrageOpportunity,
    DepthCheckConfig,
    OrderBookLevel,
    OrderBookSnapshot,
)
from app.services.depth_check import (
    apply_depth_checks,
    calculate_depth_result,
    simulate_notional_fill,
)


class DepthCheckFillTests(unittest.TestCase):
    def test_simulates_buy_fill_from_asks_low_to_high(self) -> None:
        result = simulate_notional_fill(
            [
                OrderBookLevel(price=100.0, quantity=5.0),
                OrderBookLevel(price=101.0, quantity=10.0),
            ],
            target_notional_usd=1000.0,
            side="buy",
        )

        expected_price = 1000.0 / (5.0 + (500.0 / 101.0))
        self.assertTrue(result.can_fill)
        self.assertAlmostEqual(result.effective_price, expected_price)
        self.assertAlmostEqual(result.slippage_percent, 0.4975124378)

    def test_simulates_sell_fill_from_bids_high_to_low(self) -> None:
        result = simulate_notional_fill(
            [
                OrderBookLevel(price=100.0, quantity=5.0),
                OrderBookLevel(price=99.0, quantity=10.0),
            ],
            target_notional_usd=1000.0,
            side="sell",
        )

        expected_price = 1000.0 / (5.0 + (500.0 / 99.0))
        self.assertTrue(result.can_fill)
        self.assertAlmostEqual(result.effective_price, expected_price)
        self.assertAlmostEqual(result.slippage_percent, 0.5025125628)

    def test_marks_insufficient_depth_when_target_cannot_fill(self) -> None:
        result = simulate_notional_fill(
            [OrderBookLevel(price=100.0, quantity=5.0)],
            target_notional_usd=1000.0,
            side="buy",
        )

        self.assertFalse(result.can_fill)
        self.assertIsNone(result.effective_price)
        self.assertIsNone(result.slippage_percent)
        self.assertEqual(result.filled_notional_usd, 500.0)

    def test_calculates_depth_adjusted_spread_and_net_spread(self) -> None:
        opportunity = _opportunity()
        result = calculate_depth_result(
            opportunity=opportunity,
            long_order_book=_order_book(
                "Binance",
                asks=[
                    OrderBookLevel(price=100.0, quantity=5.0),
                    OrderBookLevel(price=101.0, quantity=10.0),
                ],
                bids=[OrderBookLevel(price=99.0, quantity=20.0)],
            ),
            short_order_book=_order_book(
                "Bybit",
                asks=[OrderBookLevel(price=103.0, quantity=20.0)],
                bids=[
                    OrderBookLevel(price=102.0, quantity=5.0),
                    OrderBookLevel(price=101.0, quantity=10.0),
                ],
            ),
            depth_config=DepthCheckConfig(
                enabled=True,
                target_notional_usd=1000.0,
                max_allowed_slippage_percent=1.0,
            ),
        )

        expected_long = 1000.0 / (5.0 + (500.0 / 101.0))
        expected_short = 1000.0 / (5.0 + (490.0 / 101.0))
        expected_raw = (expected_short - expected_long) / expected_long * 100

        self.assertEqual(result.depth_status, "OK")
        self.assertTrue(result.can_fill_long)
        self.assertTrue(result.can_fill_short)
        self.assertEqual(result.long_effective_price, round(expected_long, 4))
        self.assertEqual(result.short_effective_price, round(expected_short, 4))
        self.assertEqual(result.depth_adjusted_raw_spread_percent, round(expected_raw, 4))
        self.assertEqual(
            result.depth_adjusted_net_spread_percent,
            round(expected_raw - opportunity.estimated_fee_percent, 4),
        )

    def test_marks_thin_when_slippage_exceeds_limit(self) -> None:
        result = calculate_depth_result(
            opportunity=_opportunity(),
            long_order_book=_order_book(
                "Binance",
                asks=[
                    OrderBookLevel(price=100.0, quantity=5.0),
                    OrderBookLevel(price=101.0, quantity=10.0),
                ],
                bids=[OrderBookLevel(price=99.0, quantity=20.0)],
            ),
            short_order_book=_order_book(
                "Bybit",
                asks=[OrderBookLevel(price=103.0, quantity=20.0)],
                bids=[OrderBookLevel(price=102.0, quantity=20.0)],
            ),
            depth_config=DepthCheckConfig(
                enabled=True,
                target_notional_usd=1000.0,
                max_allowed_slippage_percent=0.3,
            ),
        )

        self.assertEqual(result.depth_status, "Thin")
        self.assertIn("Long slippage exceeds 0.3000%", result.depth_reasons)


class DepthCheckApplicationTests(unittest.IsolatedAsyncioTestCase):
    async def test_depth_disabled_does_not_change_existing_opportunities(self) -> None:
        opportunities = [_opportunity()]

        result = await apply_depth_checks(
            opportunities,
            connectors=[],
            depth_config=DepthCheckConfig(enabled=False),
        )

        self.assertIs(result, opportunities)
        self.assertIsNone(result[0].depth_check)

    async def test_missing_public_depth_connector_marks_unknown_and_keeps_opportunity(self) -> None:
        opportunities = [_opportunity()]

        result = await apply_depth_checks(
            opportunities,
            connectors=[],
            depth_config=DepthCheckConfig(enabled=True),
        )

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].depth_check.depth_status, "Unknown")
        self.assertEqual(result[0].symbol, opportunities[0].symbol)


def _order_book(
    exchange: str,
    asks: list[OrderBookLevel],
    bids: list[OrderBookLevel],
) -> OrderBookSnapshot:
    return OrderBookSnapshot(
        exchange=exchange,
        symbol="BTCUSDT",
        bids=bids,
        asks=asks,
        timestamp=datetime.now(timezone.utc),
    )


def _opportunity() -> ArbitrageOpportunity:
    return ArbitrageOpportunity(
        symbol="BTCUSDT",
        long_exchange="Binance",
        short_exchange="Bybit",
        ask_price=100.0,
        bid_price=102.0,
        raw_spread_percent=2.0,
        estimated_net_spread_percent=1.8,
        estimated_fee_percent=0.2,
        volume_24h_usd=1_000_000,
        best_ask_size=5.0,
        best_bid_size=5.0,
        long_funding_rate_percent=0.01,
        short_funding_rate_percent=0.02,
        funding_rate_difference_percent=0.01,
        next_funding_time=None,
        funding_impact="Good",
        liquidity_status="OK",
        timestamp=datetime.now(timezone.utc),
    )


if __name__ == "__main__":
    unittest.main()
