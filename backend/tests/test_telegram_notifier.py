import unittest
from datetime import datetime, timezone

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
        self.assertIn("Arbitrage Alert: SPACEUSDT", payload["text"])
        self.assertIn("Long: Binance", payload["text"])
        self.assertIn("Depth-adjusted net: 0.1400%", payload["text"])
        self.assertEqual(timeout, 10)
        self.assertEqual(status.sent_count, 1)
        self.assertIsNotNone(status.last_sent_at)
        self.assertIsNone(status.last_error)

    async def test_duplicate_alert_id_is_not_sent_twice(self) -> None:
        sender = RecordingSender()
        notifier = TelegramNotifier(
            sender=sender.send,
            env_provider=lambda key: {"TELEGRAM_BOT_TOKEN": "token", "TELEGRAM_CHAT_ID": "chat"}.get(key),
        )
        config = TelegramDisplaySettings(enabled=True)
        alert = _alert()

        first_sent = await notifier.send_alerts([alert], config)
        second_sent = await notifier.send_alerts([alert], config)

        self.assertEqual(first_sent, 1)
        self.assertEqual(second_sent, 0)
        self.assertEqual(len(sender.calls), 1)

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
        self.assertIn("network down", status.last_error)
        self.assertNotIn("token", status.last_error)
        self.assertNotIn("chat", status.last_error)

    def test_formats_alert_message_without_trade_commands(self) -> None:
        message = format_alert_message(_alert())

        self.assertIn("Arbitrage Alert: SPACEUSDT", message)
        self.assertIn("Raw spread: 0.4900%", message)
        self.assertIn("Severity: Strong", message)
        self.assertNotIn("buy", message.lower())
        self.assertNotIn("execute", message.lower())


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


def _alert() -> AlertCandidate:
    return AlertCandidate(
        id="SPACEUSDT:Binance:Bybit:1760000000",
        symbol="SPACEUSDT",
        long_exchange="Binance",
        short_exchange="Bybit",
        raw_spread_percent=0.49,
        estimated_net_spread_percent=0.28,
        depth_adjusted_net_spread_percent=0.14,
        depth_status="OK",
        target_notional_usd=500,
        long_slippage_percent=0.03,
        short_slippage_percent=0.04,
        funding_impact="Good",
        liquidity_status="OK",
        alert_score=12.5,
        severity="Strong",
        reasons=[
            "Net spread above alert threshold",
            "Depth-adjusted spread remains positive",
            "Target notional fills on both sides",
        ],
        created_at=datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc),
        suppressed=False,
    )


if __name__ == "__main__":
    unittest.main()
