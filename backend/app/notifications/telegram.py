import asyncio
import json
import os
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from typing import Awaitable, Callable
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from app.domain.models import (
    AlertCandidate,
    TelegramDisplaySettings,
    TelegramStatusResponse,
)


PROJECT_ROOT = Path(__file__).resolve().parents[3]
ENV_FILE_PATH = PROJECT_ROOT / ".env"
TelegramSender = Callable[[str, dict[str, str], int], Awaitable[None]]
EnvProvider = Callable[[str], str | None]


class TelegramNotifier:
    def __init__(
        self,
        sender: TelegramSender | None = None,
        env_provider: EnvProvider | None = None,
    ) -> None:
        self._sender = sender or _send_telegram_message
        self._env_provider = env_provider or _env_value
        self._sent_alert_ids: set[str] = set()
        self._last_sent_at: datetime | None = None
        self._sent_count = 0
        self._last_error: str | None = None
        self._lock = asyncio.Lock()

    async def send_alerts(
        self,
        alerts: list[AlertCandidate],
        config: TelegramDisplaySettings,
    ) -> int:
        if not config.enabled:
            return 0

        bot_token = self._env_provider(config.bot_token_env)
        chat_id = self._env_provider(config.chat_id_env)
        if not bot_token or not chat_id:
            await self._set_error(
                "Telegram is enabled but required environment variables are missing: "
                f"{config.bot_token_env}, {config.chat_id_env}"
            )
            return 0

        sent = 0
        for alert in alerts:
            if alert.suppressed:
                continue

            async with self._lock:
                if alert.id in self._sent_alert_ids:
                    continue

            message = format_alert_message(alert)
            payload = {
                "chat_id": chat_id,
                "text": message,
                "parse_mode": config.parse_mode,
                "disable_web_page_preview": "true",
            }
            try:
                await self._sender(
                    f"https://api.telegram.org/bot{bot_token}/sendMessage",
                    payload,
                    config.timeout_seconds,
                )
            except Exception as exc:
                await self._set_error(
                    f"Telegram send failed: {_safe_error_message(exc, bot_token, chat_id)}"
                )
                continue

            async with self._lock:
                self._sent_alert_ids.add(alert.id)
                self._last_sent_at = datetime.now(timezone.utc)
                self._sent_count += 1
                self._last_error = None
                sent += 1

        return sent

    async def get_status(
        self,
        config: TelegramDisplaySettings,
    ) -> TelegramStatusResponse:
        configured = bool(
            self._env_provider(config.bot_token_env)
            and self._env_provider(config.chat_id_env)
        )
        async with self._lock:
            return TelegramStatusResponse(
                enabled=config.enabled,
                configured=configured,
                last_sent_at=self._last_sent_at,
                sent_count=self._sent_count,
                last_error=self._last_error,
            )

    async def _set_error(self, message: str) -> None:
        async with self._lock:
            self._last_error = message


def format_alert_message(alert: AlertCandidate) -> str:
    lines = [
        f"<b>Arbitrage Alert: {escape(alert.symbol)}</b>",
        "",
        f"Long: {escape(alert.long_exchange)}",
        f"Short: {escape(alert.short_exchange)}",
        "",
        f"Raw spread: {_format_percent(alert.raw_spread_percent)}",
        f"Net spread: {_format_percent(alert.estimated_net_spread_percent)}",
    ]
    if alert.depth_adjusted_net_spread_percent is not None:
        lines.append(
            "Depth-adjusted net: "
            f"{_format_percent(alert.depth_adjusted_net_spread_percent)}"
        )
    if alert.depth_status:
        depth_line = f"Depth: {escape(alert.depth_status)}"
        if alert.target_notional_usd is not None:
            depth_line += f" for ${alert.target_notional_usd:,.0f}"
        lines.append(depth_line)
    if (
        alert.long_slippage_percent is not None
        or alert.short_slippage_percent is not None
    ):
        lines.append(
            "Slippage L/S: "
            f"{_format_optional_percent(alert.long_slippage_percent)} / "
            f"{_format_optional_percent(alert.short_slippage_percent)}"
        )

    lines.extend(
        [
            "",
            f"Funding: {escape(alert.funding_impact)}",
            f"Severity: {escape(alert.severity)}",
            f"Timestamp: {alert.created_at.isoformat()}",
        ]
    )
    if alert.reasons:
        lines.extend(["", "Reasons:"])
        lines.extend(f"- {escape(reason)}" for reason in alert.reasons[:6])

    return "\n".join(lines)


async def _send_telegram_message(
    url: str,
    payload: dict[str, str],
    timeout_seconds: int,
) -> None:
    await asyncio.to_thread(_send_telegram_message_sync, url, payload, timeout_seconds)


def _send_telegram_message_sync(
    url: str,
    payload: dict[str, str],
    timeout_seconds: int,
) -> None:
    encoded_payload = urlencode(payload).encode("utf-8")
    request = Request(
        url,
        data=encoded_payload,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "crypto-arb-scanner/0.1",
        },
        method="POST",
    )
    with urlopen(request, timeout=timeout_seconds) as response:
        response_payload = json.loads(response.read().decode("utf-8"))

    if not isinstance(response_payload, dict) or not response_payload.get("ok"):
        description = (
            response_payload.get("description")
            if isinstance(response_payload, dict)
            else "unknown Telegram API error"
        )
        raise RuntimeError(description or "Telegram API request failed")


def _env_value(name: str) -> str | None:
    value = os.getenv(name)
    if value:
        return value

    return _env_file_values().get(name)


def _env_file_values() -> dict[str, str]:
    if not ENV_FILE_PATH.exists():
        return {}

    values: dict[str, str] = {}
    try:
        lines = ENV_FILE_PATH.read_text(encoding="utf-8").splitlines()
    except OSError:
        return {}

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            values[key] = value
    return values


def _safe_error_message(
    exc: Exception,
    bot_token: str,
    chat_id: str,
) -> str:
    message = str(exc)
    for secret_value in (bot_token, chat_id):
        if secret_value:
            message = message.replace(secret_value, "[redacted]")
    return message


def _format_percent(value: float) -> str:
    return f"{value:.4f}%"


def _format_optional_percent(value: float | None) -> str:
    if value is None:
        return "-"
    return _format_percent(value)
