import tempfile
import unittest
from pathlib import Path

from app.core.config import load_app_config
from app.domain.models import MarketSnapshot, ScannerFilters
from app.services.spread_engine import calculate_opportunities


class ConfigLoadingTests(unittest.TestCase):
    def test_loads_config_yaml_before_example(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = root / "config.yaml"
            example_path = root / "config.example.yaml"
            config_path.write_text(
                """
fees:
  Binance:
    maker_percent: 0.01
    taker_percent: 0.10
filters:
  min_raw_spread: 0.25
  min_net_spread: 0.05
  min_volume_24h_usd: 123456
  enabled_exchanges:
    - Binance
telegram:
  enabled: true
  alert_cooldown_seconds: 45
  bot_token: should-not-be-exposed
""",
                encoding="utf-8",
            )
            example_path.write_text(
                """
fees:
  Bybit:
    maker_percent: 0.02
    taker_percent: 0.02
""",
                encoding="utf-8",
            )

            config = load_app_config(config_path=config_path, example_path=example_path)

        self.assertEqual(config.fees["Binance"].taker_percent, 0.10)
        self.assertEqual(config.default_filters.min_raw_spread, 0.25)
        self.assertEqual(config.default_filters.min_net_spread, 0.05)
        self.assertEqual(config.default_filters.min_volume_24h_usd, 123456)
        self.assertEqual(config.default_filters.exchanges, ("Binance",))
        self.assertEqual(config.data_source_mode, "mock")
        self.assertEqual(config.enabled_connectors, ("fake",))
        self.assertEqual(config.symbol_selection.mode, "manual")
        self.assertEqual(config.symbol_selection.min_volume_24h_usd, 123456)
        self.assertEqual(config.symbol_selection.max_symbols, 10)
        self.assertEqual(config.symbol_selection.min_exchanges_required, 2)
        self.assertTrue(config.telegram.enabled)
        self.assertEqual(config.telegram.alert_cooldown_seconds, 45)
        self.assertFalse(hasattr(config.telegram, "bot_token"))

    def test_falls_back_to_example_when_config_yaml_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = root / "config.yaml"
            example_path = root / "config.example.yaml"
            example_path.write_text(
                """
fees:
  OKX:
    maker_percent: 0.01
    taker_percent: 0.07
filters:
  min_raw_spread: 0.15
  min_net_spread: -0.02
  min_volume_24h_usd: 500000
  enabled_exchanges:
    - OKX
    - Bitget
""",
                encoding="utf-8",
            )

            config = load_app_config(config_path=config_path, example_path=example_path)

        self.assertEqual(config.fees["OKX"].taker_percent, 0.07)
        self.assertEqual(config.default_filters.exchanges, ("OKX", "Bitget"))

    def test_uses_builtin_defaults_when_config_files_are_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = load_app_config(
                config_path=root / "config.yaml",
                example_path=root / "config.example.yaml",
            )

        self.assertIn("Binance", config.fees)
        self.assertEqual(config.data_source_mode, "mock")
        self.assertEqual(config.enabled_connectors, ("fake",))
        self.assertEqual(config.max_symbols, 10)
        self.assertEqual(config.symbol_allowlist, ("BTCUSDT", "ETHUSDT", "SOLUSDT"))
        self.assertEqual(config.symbol_selection.mode, "manual")
        self.assertEqual(config.symbol_selection.max_symbols, 10)
        self.assertEqual(config.default_filters.min_raw_spread, 0.10)
        self.assertEqual(config.default_filters.min_volume_24h_usd, 400_000)
        self.assertFalse(config.depth_check.enabled)
        self.assertEqual(config.depth_check.target_notional_usd, 1000)
        self.assertEqual(config.depth_check.max_opportunities_to_check, 10)
        self.assertEqual(config.depth_check.order_book_limit, 50)
        self.assertEqual(config.depth_check.max_allowed_slippage_percent, 0.3)
        self.assertFalse(config.alerts.enabled)
        self.assertEqual(config.alerts.min_net_spread_percent, 0.15)
        self.assertEqual(config.alerts.min_depth_adjusted_net_spread_percent, 0.05)
        self.assertEqual(config.alerts.require_depth_status, ("OK", "Thin"))
        self.assertEqual(config.alerts.max_allowed_slippage_percent, 0.3)
        self.assertEqual(config.alerts.min_volume_24h_usd, 400_000)
        self.assertEqual(config.alerts.cooldown_seconds, 300)
        self.assertEqual(config.alerts.max_alerts_per_scan, 5)

    def test_loads_live_data_source_mode_as_reserved_config_value(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = root / "config.yaml"
            config_path.write_text(
                """
data_source_mode: live
enabled_connectors:
  - binance
max_symbols: 2
symbol_allowlist:
  - BTCUSDT
  - ETHUSDT
""",
                encoding="utf-8",
            )

            config = load_app_config(
                config_path=config_path,
                example_path=root / "config.example.yaml",
            )

        self.assertEqual(config.data_source_mode, "live")
        self.assertEqual(config.enabled_connectors, ("binance",))
        self.assertEqual(config.max_symbols, 2)
        self.assertEqual(config.symbol_allowlist, ("BTCUSDT", "ETHUSDT"))
        self.assertEqual(config.symbol_selection.mode, "manual")

    def test_loads_symbol_selection_auto_config(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = root / "config.yaml"
            config_path.write_text(
                """
data_source_mode: live
enabled_connectors:
  - binance
  - bybit
max_symbols: 3
symbol_allowlist:
  - BTCUSDT
symbol_selection:
  mode: auto
  min_volume_24h_usd: 400000
  max_volume_24h_usd: 50000000
  max_symbols: 100
  min_exchanges_required: 3
  include_symbols:
    - SOLUSDT
  exclude_symbols:
    - BTCUSDT
    - ETHUSDT
""",
                encoding="utf-8",
            )

            config = load_app_config(
                config_path=config_path,
                example_path=root / "config.example.yaml",
            )

        self.assertEqual(config.symbol_selection.mode, "auto")
        self.assertEqual(config.symbol_selection.min_volume_24h_usd, 400_000)
        self.assertEqual(config.symbol_selection.max_volume_24h_usd, 50_000_000)
        self.assertEqual(config.symbol_selection.max_symbols, 100)
        self.assertEqual(config.symbol_selection.min_exchanges_required, 3)
        self.assertEqual(config.symbol_selection.include_symbols, ("SOLUSDT",))
        self.assertEqual(config.symbol_selection.exclude_symbols, ("BTCUSDT", "ETHUSDT"))

    def test_loads_depth_check_config(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = root / "config.yaml"
            config_path.write_text(
                """
depth_check:
  enabled: true
  target_notional_usd: 1500
  max_opportunities_to_check: 5
  order_book_limit: 100
  max_allowed_slippage_percent: 0.25
""",
                encoding="utf-8",
            )

            config = load_app_config(
                config_path=config_path,
                example_path=root / "config.example.yaml",
            )

        self.assertTrue(config.depth_check.enabled)
        self.assertEqual(config.depth_check.target_notional_usd, 1500)
        self.assertEqual(config.depth_check.max_opportunities_to_check, 5)
        self.assertEqual(config.depth_check.order_book_limit, 100)
        self.assertEqual(config.depth_check.max_allowed_slippage_percent, 0.25)

    def test_loads_alert_config(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = root / "config.yaml"
            config_path.write_text(
                """
alerts:
  enabled: true
  min_net_spread_percent: 0.20
  min_depth_adjusted_net_spread_percent: 0.08
  require_depth_status:
    - OK
  max_allowed_slippage_percent: 0.25
  min_volume_24h_usd: 750000
  cooldown_seconds: 120
  max_alerts_per_scan: 3
""",
                encoding="utf-8",
            )

            config = load_app_config(
                config_path=config_path,
                example_path=root / "config.example.yaml",
            )

        self.assertTrue(config.alerts.enabled)
        self.assertEqual(config.alerts.min_net_spread_percent, 0.20)
        self.assertEqual(config.alerts.min_depth_adjusted_net_spread_percent, 0.08)
        self.assertEqual(config.alerts.require_depth_status, ("OK",))
        self.assertEqual(config.alerts.max_allowed_slippage_percent, 0.25)
        self.assertEqual(config.alerts.min_volume_24h_usd, 750_000)
        self.assertEqual(config.alerts.cooldown_seconds, 120)
        self.assertEqual(config.alerts.max_alerts_per_scan, 3)

    def test_live_data_source_mode_defaults_to_public_connectors(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = root / "config.yaml"
            config_path.write_text(
                """
data_source_mode: live
""",
                encoding="utf-8",
            )

            config = load_app_config(
                config_path=config_path,
                example_path=root / "config.example.yaml",
            )

        self.assertEqual(config.data_source_mode, "live")
        self.assertEqual(config.enabled_connectors, ("binance", "bybit"))

    def test_loaded_fees_are_used_by_spread_calculation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = root / "config.yaml"
            config_path.write_text(
                """
fees:
  Cheap:
    maker_percent: 0.00
    taker_percent: 0.01
  Expensive:
    maker_percent: 0.00
    taker_percent: 0.20
filters:
  enabled_exchanges:
    - Cheap
    - Expensive
""",
                encoding="utf-8",
            )
            config = load_app_config(
                config_path=config_path,
                example_path=root / "config.example.yaml",
            )

        opportunities = calculate_opportunities(
            snapshots=[
                _snapshot("Cheap", bid=99.0, ask=100.0),
                _snapshot("Expensive", bid=101.0, ask=102.0),
            ],
            fees_by_exchange=config.fees,
            filters=ScannerFilters(exchanges=("Cheap", "Expensive")),
        )

        self.assertEqual(len(opportunities), 1)
        self.assertEqual(opportunities[0].raw_spread_percent, 1.0)
        self.assertEqual(opportunities[0].estimated_net_spread_percent, 0.58)


def _snapshot(exchange: str, bid: float, ask: float) -> MarketSnapshot:
    from datetime import datetime, timezone

    return MarketSnapshot(
        exchange=exchange,
        symbol="BTCUSDT",
        best_bid=bid,
        best_bid_size=10.0,
        best_ask=ask,
        best_ask_size=10.0,
        volume_24h_usd=1_000_000,
        funding_rate_percent=0.01,
        next_funding_time=None,
        timestamp=datetime.now(timezone.utc),
    )


if __name__ == "__main__":
    unittest.main()
