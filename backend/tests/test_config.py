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
        self.assertEqual(config.default_filters.min_raw_spread, 0.10)
        self.assertEqual(config.default_filters.min_volume_24h_usd, 400_000)

    def test_loads_live_data_source_mode_as_reserved_config_value(self) -> None:
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
