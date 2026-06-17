import unittest
from datetime import datetime, timedelta, timezone

from app.domain.models import (
    AlertConfig,
    ArbitrageOpportunity,
    DepthCheckResult,
)
from app.services.alert_engine import AlertEngine


class AlertEngineTests(unittest.IsolatedAsyncioTestCase):
    async def test_alerts_disabled_produces_no_active_alerts(self) -> None:
        engine = AlertEngine()

        active = await engine.evaluate(
            [_opportunity(net_spread=1.0)],
            AlertConfig(enabled=False),
            depth_check_enabled=False,
            evaluated_at=_now(),
        )

        self.assertEqual(active, [])
        self.assertEqual(await engine.get_active_alerts(), [])

    async def test_positive_opportunity_above_threshold_creates_alert_candidate(self) -> None:
        engine = AlertEngine()

        active = await engine.evaluate(
            [_opportunity(net_spread=0.30)],
            _alert_config(),
            depth_check_enabled=False,
            evaluated_at=_now(),
        )

        self.assertEqual(len(active), 1)
        self.assertEqual(active[0].symbol, "BTCUSDT")
        self.assertFalse(active[0].suppressed)
        self.assertIn("Net spread above alert threshold", active[0].reasons)

    async def test_depth_adjusted_spread_is_preferred_when_available(self) -> None:
        engine = AlertEngine()
        opportunity = _opportunity(
            net_spread=0.01,
            depth_check=_depth_check(
                depth_adjusted_net_spread_percent=0.08,
                depth_status="OK",
            ),
        )

        active = await engine.evaluate(
            [opportunity],
            _alert_config(min_net_spread_percent=0.15),
            depth_check_enabled=True,
            evaluated_at=_now(),
        )

        self.assertEqual(len(active), 1)
        self.assertEqual(active[0].depth_adjusted_net_spread_percent, 0.08)
        self.assertIn("Depth-adjusted spread remains positive", active[0].reasons)

    async def test_insufficient_depth_suppresses_alert(self) -> None:
        engine = AlertEngine()
        opportunity = _opportunity(
            net_spread=0.50,
            depth_check=_depth_check(
                depth_adjusted_net_spread_percent=None,
                depth_status="Insufficient",
            ),
        )

        active = await engine.evaluate(
            [opportunity],
            _alert_config(),
            depth_check_enabled=True,
            evaluated_at=_now(),
        )
        history = await engine.get_history()

        self.assertEqual(active, [])
        self.assertEqual(history[0].suppression_reason, "Suppressed because depth is insufficient")

    async def test_cooldown_suppresses_duplicate_alert(self) -> None:
        engine = AlertEngine()
        first_scan = _now()
        config = _alert_config(cooldown_seconds=300)

        first_active = await engine.evaluate(
            [_opportunity(net_spread=0.40)],
            config,
            depth_check_enabled=False,
            evaluated_at=first_scan,
        )
        second_active = await engine.evaluate(
            [_opportunity(net_spread=0.45)],
            config,
            depth_check_enabled=False,
            evaluated_at=first_scan + timedelta(seconds=60),
        )
        history = await engine.get_history()

        self.assertEqual(len(first_active), 1)
        self.assertEqual(second_active, [])
        self.assertEqual(history[0].suppression_reason, "Suppressed by cooldown")

    async def test_max_alerts_per_scan_is_respected(self) -> None:
        engine = AlertEngine()

        active = await engine.evaluate(
            [
                _opportunity("BTCUSDT", net_spread=0.30),
                _opportunity("ETHUSDT", net_spread=0.50),
                _opportunity("SOLUSDT", net_spread=0.40),
            ],
            _alert_config(max_alerts_per_scan=2),
            depth_check_enabled=False,
            evaluated_at=_now(),
        )

        self.assertEqual(len(active), 2)
        self.assertEqual([alert.symbol for alert in active], ["ETHUSDT", "SOLUSDT"])

    async def test_weak_negative_net_spread_does_not_create_active_alert(self) -> None:
        engine = AlertEngine()

        active = await engine.evaluate(
            [_opportunity(net_spread=-0.10)],
            _alert_config(),
            depth_check_enabled=False,
            evaluated_at=_now(),
        )
        history = await engine.get_history()

        self.assertEqual(active, [])
        self.assertEqual(history[0].suppression_reason, "Suppressed because net spread below threshold")

    async def test_unknown_depth_is_allowed_only_when_depth_check_disabled(self) -> None:
        engine = AlertEngine()
        opportunity = _opportunity(
            net_spread=0.40,
            depth_check=_depth_check(
                depth_adjusted_net_spread_percent=None,
                depth_status="Unknown",
            ),
        )

        active_enabled = await engine.evaluate(
            [opportunity],
            _alert_config(),
            depth_check_enabled=True,
            evaluated_at=_now(),
        )
        active_disabled = await engine.evaluate(
            [opportunity],
            _alert_config(cooldown_seconds=0),
            depth_check_enabled=False,
            evaluated_at=_now() + timedelta(seconds=1),
        )

        self.assertEqual(active_enabled, [])
        self.assertEqual(len(active_disabled), 1)


def _alert_config(**overrides: object) -> AlertConfig:
    values = {
        "enabled": True,
        "min_net_spread_percent": 0.15,
        "min_depth_adjusted_net_spread_percent": 0.05,
        "require_depth_status": ("OK", "Thin"),
        "max_allowed_slippage_percent": 0.3,
        "min_volume_24h_usd": 400_000,
        "cooldown_seconds": 300,
        "max_alerts_per_scan": 5,
    }
    values.update(overrides)
    return AlertConfig(**values)


def _opportunity(
    symbol: str = "BTCUSDT",
    net_spread: float = 0.30,
    depth_check: DepthCheckResult | None = None,
) -> ArbitrageOpportunity:
    return ArbitrageOpportunity(
        symbol=symbol,
        long_exchange="Binance",
        short_exchange="Bybit",
        ask_price=100.0,
        bid_price=101.0,
        raw_spread_percent=1.0,
        estimated_net_spread_percent=net_spread,
        estimated_fee_percent=0.20,
        volume_24h_usd=1_000_000,
        best_ask_size=10.0,
        best_bid_size=10.0,
        long_funding_rate_percent=0.01,
        short_funding_rate_percent=0.02,
        funding_rate_difference_percent=0.01,
        next_funding_time=None,
        funding_impact="Good",
        liquidity_status="OK",
        depth_check=depth_check,
        timestamp=_now(),
    )


def _depth_check(
    depth_adjusted_net_spread_percent: float | None,
    depth_status: str,
) -> DepthCheckResult:
    return DepthCheckResult(
        target_notional_usd=1000,
        can_fill_long=depth_status != "Insufficient",
        can_fill_short=depth_status != "Insufficient",
        long_effective_price=100.0 if depth_status != "Insufficient" else None,
        short_effective_price=101.0 if depth_status != "Insufficient" else None,
        long_slippage_percent=0.05 if depth_status != "Insufficient" else None,
        short_slippage_percent=0.04 if depth_status != "Insufficient" else None,
        depth_adjusted_raw_spread_percent=0.28 if depth_adjusted_net_spread_percent is not None else None,
        depth_adjusted_net_spread_percent=depth_adjusted_net_spread_percent,
        depth_status=depth_status,
        depth_reasons=[],
    )


def _now() -> datetime:
    return datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)


if __name__ == "__main__":
    unittest.main()
