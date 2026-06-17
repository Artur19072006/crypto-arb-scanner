import unittest
from datetime import datetime, timedelta, timezone

from app.domain.models import AlertCandidate, TelegramDisplaySettings
from app.notifications.telegram import TelegramNotifier, format_alert_message


class TelegramNotifierTests(unittest.IsolatedAsyncioTestCase):
    async def test_telegram_disabled_sends_nothing(self) -> None:
        sender = RecordingSender()
        notifier = TelegramNotifier(
            sender=sender.send,
            env_provider=lambda key: {"TELEGRAM_BOT_TOKEN": "token", "TELEGRAM_CHAT_ID": "chat"}.get(key),
        )

        sent = await notifier.send_alerts([_alert()], TelegramDisplaySettings(enabled=False))
        status = await notifier.get_status(TelegramDisplaySettings(enabled=False))

        self.assertEqual(sent, 0)
        self.assertEqual(sender.calls, [])
        self.assertFalse(status.enabled)
        self.assertTrue(status.configured)
        self.assertEqual(status.tracked_alert_keys_count, 0)

    async def test_enabled_with_missing_env_does_not_crash_and_reports_not_configured(self) -> None:
        notifier = TelegramNotifier(
            sender=RecordingSender().send,
            env_provider=lambda key: None,
        )
        config = TelegramDisplaySettings(enabled=True)

        sent = await notifier.send_alerts([_alert()], config)
        status = await notifier.get_status(config)

        self.assertEqual(sent, 0)
        self.assertFalse(status.configured)
        self.assertIn("environment variables are missing", status.last_error)
        self.assertEqual(status.tracked_alert_keys_count, 0)

    async def test_sends_formatted_message_for_active_alert(self) -> None:
        sender = RecordingSender()
        notifier = TelegramNotifier(
            sender=sender.send,
            env_provider=lambda key: {"TELEGRAM_BOT_TOKEN": "token", "TELEGRAM_CHAT_ID": "chat"}.get(key),
        )

        sent = await notifier.send_alerts([_alert()], TelegramDisplaySettings(enabled=True))
        status = await notifier.get_status(TelegramDisplaySettings(enabled=True))

        self.assertEqual(sent, 1)
        self.assertEqual(len(sender.calls), 1)
        url, payload, timeout = sender.calls[0]
        self.assertEqual(url, "https://api.telegram.org/bottoken/sendMessage")
        self.assertEqual(payload["chat_id"], "chat")
        self.assertEqual(payload["parse_mode"], "HTML")
        self.assertIn("<b>SPACEUSDT</b>", payload["text"])
        self.assertIn(
            '<a href="https://www.binance.com/en/futures/SPACEUSDT">Binance</a> - <b>LONG</b>',
            payload["text"],
        )
        self.assertIn("Ask: 0.19694", payload["text"])
        self.assertIn("Funding: -0.1234%", payload["text"])
        self.assertIn(
            '<a href="https://www.bybit.com/trade/usdt/SPACEUSDT">Bybit</a> - <b>SHORT</b>',
            payload["text"],
        )
        self.assertIn("Bid: 0.19755", payload["text"])
        self.assertIn("Funding: -0.0842%", payload["text"])
        self.assertIn("Depth net: 0.1400%", payload["text"])
        self.assertIn("Fees: 0.2100%", payload["text"])
        self.assertIn("Funding diff: -0.0392%", payload["text"])
        self.assertIn("Next funding: 2026-06-17 12:00 UTC", payload["text"])
        self.assertIn("24h volume: $1,234,567", payload["text"])
        self.assertEqual(timeout, 10)
        self.assertEqual(status.sent_count, 1)
        self.assertIsNotNone(status.last_sent_at)
        self.assertIsNone(status.last_error)
        self.assertEqual(status.tracked_alert_keys_count, 1)

    async def test_same_alert_key_within_cooldown_sends_once_even_when_id_changes(self) -> None:
        sender = RecordingSender()
        notifier = TelegramNotifier(
            sender=sender.send,
            env_provider=lambda key: {"TELEGRAM_BOT_TOKEN": "token", "TELEGRAM_CHAT_ID": "chat"}.get(key),
        )
        config = TelegramDisplaySettings(enabled=True)
        first_alert = _alert(alert_id="SPACEUSDT:Binance:Bybit:1760000000")
        second_alert = _alert(alert_id="SPACEUSDT:Binance:Bybit:1760000060")
        first_scan = _now()

        first_sent = await notifier.send_alerts(
            [first_alert],
            config,
            cooldown_seconds=300,
            now=first_scan,
        )
        second_sent = await notifier.send_alerts(
            [second_alert],
            config,
            cooldown_seconds=300,
            now=first_scan + timedelta(seconds=60),
        )
        status = await notifier.get_status(config)

        self.assertEqual(first_sent, 1)
        self.assertEqual(second_sent, 0)
        self.assertEqual(len(sender.calls), 1)
        self.assertEqual(status.sent_count, 1)
        self.assertEqual(status.tracked_alert_keys_count, 1)

    async def test_same_alert_key_after_cooldown_can_send_again(self) -> None:
        sender = RecordingSender()
        notifier = TelegramNotifier(
            sender=sender.send,
            env_provider=lambda key: {"TELEGRAM_BOT_TOKEN": "token", "TELEGRAM_CHAT_ID": "chat"}.get(key),
        )
        config = TelegramDisplaySettings(enabled=True)
        alert = _alert(alert_id="SPACEUSDT:Binance:Bybit:stable-id")
        first_scan = _now()

        first_sent = await notifier.send_alerts(
            [alert],
            config,
            cooldown_seconds=300,
            now=first_scan,
        )
        second_sent = await notifier.send_alerts(
            [alert],
            config,
            cooldown_seconds=300,
            now=first_scan + timedelta(seconds=301),
        )
        status = await notifier.get_status(config)

        self.assertEqual(first_sent, 1)
        self.assertEqual(second_sent, 1)
        self.assertEqual(len(sender.calls), 2)
        self.assertEqual(status.sent_count, 2)
        self.assertEqual(status.tracked_alert_keys_count, 1)

    async def test_different_alert_key_sends_separately(self) -> None:
        sender = RecordingSender()
        notifier = TelegramNotifier(
            sender=sender.send,
            env_provider=lambda key: {"TELEGRAM_BOT_TOKEN": "token", "TELEGRAM_CHAT_ID": "chat"}.get(key),
        )
        config = TelegramDisplaySettings(enabled=True)

        sent = await notifier.send_alerts(
            [_alert(), _alert(symbol="ETHUSDT")],
            config,
            cooldown_seconds=300,
            now=_now(),
        )
        status = await notifier.get_status(config)

        self.assertEqual(sent, 2)
        self.assertEqual(len(sender.calls), 2)
        self.assertEqual(status.sent_count, 2)
        self.assertEqual(status.tracked_alert_keys_count, 2)

    async def test_send_failure_stores_last_error_and_app_continues(self) -> None:
        async def failing_sender(
            url: str,
            payload: dict[str, str],
            timeout_seconds: int,
        ) -> None:
            raise RuntimeError("network down for token and chat")

        notifier = TelegramNotifier(
            sender=failing_sender,
            env_provider=lambda key: {"TELEGRAM_BOT_TOKEN": "token", "TELEGRAM_CHAT_ID": "chat"}.get(key),
        )
        config = TelegramDisplaySettings(enabled=True)

        sent = await notifier.send_alerts([_alert()], config)
        status = await notifier.get_status(config)

        self.assertEqual(sent, 0)
        self.assertEqual(status.sent_count, 0)
        self.assertEqual(status.tracked_alert_keys_count, 0)
        self.assertIn("network down", status.last_error)
        self.assertNotIn("token", status.last_error)
        self.assertNotIn("chat", status.last_error)

    def test_formats_alert_message_without_trade_commands(self) -> None:
        message = format_alert_message(_alert())

        self.assertIn("<b>SPACEUSDT</b>", message)
        self.assertIn("Raw: 0.4900%", message)
        self.assertIn("Net: 0.2800%", message)
        self.assertIn("Depth net: 0.1400%", message)
        self.assertIn("<b>SPACEUSDT</b> - <b>Strong</b>", message)
        self.assertNotIn("Reasons:", message)
        self.assertNotIn("Reason:", message)
        self.assertNotIn("buy", message.lower())
        self.assertNotIn("execute", message.lower())

    def test_formats_exchange_links_when_supported(self) -> None:
        message = format_alert_message(_alert(long_exchange="OKX", short_exchange="Unknown"))

        self.assertIn(
            '<a href="https://www.okx.com/trade-swap/space-usdt-swap">OKX</a> - <b>LONG</b>',
            message,
        )
        self.assertIn("Unknown - <b>SHORT</b>", message)

    def test_formats_alert_message_with_escaped_html(self) -> None:
        message = format_alert_message(
            _alert(
                symbol="SPACE<USDT&",
                long_exchange="Binance & Co",
                short_exchange="Bybit <Main>",
                reasons=["Depth <ok> & safe"],
            )
        )

        self.assertIn("<b>SPACE&lt;USDT&amp;</b>", message)
        self.assertIn("Binance &amp; Co - <b>LONG</b>", message)
        self.assertIn("Bybit &lt;Main&gt; - <b>SHORT</b>", message)
        self.assertNotIn("Reasons:", message)
        self.assertNotIn("Depth &lt;ok&gt; &amp; safe", message)
        self.assertNotIn("<b>SPACE<USDT&</b>", message)

    def test_formats_alert_message_skips_missing_market_fields(self) -> None:
        message = format_alert_message(
            _alert(
                ask_price=None,
                bid_price=None,
                estimated_fee_percent=None,
                long_funding_rate_percent=None,
                short_funding_rate_percent=None,
                funding_rate_difference_percent=None,
                next_funding_time=None,
                volume_24h_usd=None,
            )
        )

        self.assertNotIn("Ask:", message)
        self.assertNotIn("Bid:", message)
        self.assertNotIn("Fees:", message)
        self.assertNotIn("\nFunding:", message)
        self.assertNotIn("Funding diff:", message)
        self.assertNotIn("Next funding:", message)
        self.assertNotIn("24h volume:", message)
        self.assertNotIn("None", message)


class RecordingSender:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, str], int]] = []

    async def send(
        self,
        url: str,
        payload: dict[str, str],
        timeout_seconds: int,
    ) -> None:
        self.calls.append((url, payload, timeout_seconds))


def _alert(
    alert_id: str = "SPACEUSDT:Binance:Bybit:1760000000",
    symbol: str = "SPACEUSDT",
    long_exchange: str = "Binance",
    short_exchange: str = "Bybit",
    reasons: list[str] | None = None,
    ask_price: float | None = 0.19694,
    bid_price: float | None = 0.19755,
    estimated_fee_percent: float | None = 0.21,
    long_funding_rate_percent: float | None = -0.1234,
    short_funding_rate_percent: float | None = -0.0842,
    funding_rate_difference_percent: float | None = -0.0392,
    next_funding_time: datetime | None = datetime(
        2026,
        6,
        17,
        12,
        0,
        tzinfo=timezone.utc,
    ),
    volume_24h_usd: float | None = 1_234_567,
) -> AlertCandidate:
    return AlertCandidate(
        id=alert_id,
        alert_key=f"{symbol}:{long_exchange}:{short_exchange}",
        symbol=symbol,
        long_exchange=long_exchange,
        short_exchange=short_exchange,
        ask_price=ask_price,
        bid_price=bid_price,
        raw_spread_percent=0.49,
        estimated_net_spread_percent=0.28,
        estimated_fee_percent=estimated_fee_percent,
        depth_adjusted_net_spread_percent=0.14,
        depth_status="OK",
        target_notional_usd=500,
        long_slippage_percent=0.03,
        short_slippage_percent=0.04,
        long_funding_rate_percent=long_funding_rate_percent,
        short_funding_rate_percent=short_funding_rate_percent,
        funding_rate_difference_percent=funding_rate_difference_percent,
        next_funding_time=next_funding_time,
        volume_24h_usd=volume_24h_usd,
        funding_impact="Good",
        liquidity_status="OK",
        alert_score=12.5,
        severity="Strong",
        reasons=reasons or [
            "Net spread above alert threshold",
            "Depth-adjusted spread remains positive",
            "Target notional fills on both sides",
        ],
        created_at=datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc),
        suppressed=False,
    )


def _now() -> datetime:
    return datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)


if __name__ == "__main__":
    unittest.main()
