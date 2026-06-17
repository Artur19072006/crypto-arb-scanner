import asyncio
import json
import os
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from typing import Awaitable, Callable
from urllib.parse import quote, urlencode
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
        self._last_sent_by_alert_key: dict[str, datetime] = {}
        self._last_sent_at: datetime | None = None
        self._sent_count = 0
        self._last_error: str | None = None
        self._lock = asyncio.Lock()

    async def send_alerts(
        self,
        alerts: list[AlertCandidate],
        config: TelegramDisplaySettings,
        cooldown_seconds: int = 300,
        now: datetime | None = None,
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
        checked_at = now or datetime.now(timezone.utc)
        cooldown_seconds = max(0, cooldown_seconds)
        for alert in alerts:
            if alert.suppressed:
                continue

            alert_key = _stable_alert_key(alert)
            async with self._lock:
                if _is_within_cooldown(
                    last_sent_at=self._last_sent_by_alert_key.get(alert_key),
                    checked_at=checked_at,
                    cooldown_seconds=cooldown_seconds,
                ):
                    continue

            message = format_alert_message(alert)
            payload = {
                "chat_id": chat_id,
                "text": message,
                "parse_mode": "HTML",
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
                self._last_sent_by_alert_key[alert_key] = checked_at
                self._last_sent_at = checked_at
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
                tracked_alert_keys_count=len(self._last_sent_by_alert_key),
            )

    async def _set_error(self, message: str) -> None:
        async with self._lock:
            self._last_error = message


def format_alert_message(alert: AlertCandidate) -> str:
    lines = [
        f"<b>{escape(alert.symbol)}</b> - <b>{escape(alert.severity)}</b>",
        "",
        f"{_exchange_link(alert.long_exchange, alert.symbol)} - <b>LONG</b>",
    ]
    if alert.ask_price is not None:
        lines.append(f"Ask: {_format_price(alert.ask_price)}")
    if alert.long_funding_rate_percent is not None:
        lines.append(f"Funding: {_format_percent(alert.long_funding_rate_percent)}")

    lines.extend(
        [
            "",
            f"{_exchange_link(alert.short_exchange, alert.symbol)} - <b>SHORT</b>",
        ]
    )
    if alert.bid_price is not None:
        lines.append(f"Bid: {_format_price(alert.bid_price)}")
    if alert.short_funding_rate_percent is not None:
        lines.append(f"Funding: {_format_percent(alert.short_funding_rate_percent)}")

    lines.extend(
        [
            "",
            "<b>Spread</b>",
            f"Raw: {_format_percent(alert.raw_spread_percent)}",
            f"Net: {_format_percent(alert.estimated_net_spread_percent)}",
        ]
    )
    if alert.depth_adjusted_net_spread_percent is not None:
        lines.append(f"Depth net: {_format_percent(alert.depth_adjusted_net_spread_percent)}")
    if alert.estimated_fee_percent is not None:
        lines.append(f"Fees: {_format_percent(alert.estimated_fee_percent)}")

    if alert.depth_status:
        lines.extend(["", "<b>Depth</b>", f"Status: {escape(alert.depth_status)}"])
        if alert.target_notional_usd is not None:
            lines.append(f"Size: ${alert.target_notional_usd:,.0f}")
    if (
        alert.long_slippage_percent is not None
        or alert.short_slippage_percent is not None
    ):
        lines.append(
            "Slippage: "
            f"{_format_optional_percent(alert.long_slippage_percent)} / "
            f"{_format_optional_percent(alert.short_slippage_percent)}"
        )

    context_lines = [
        f"Funding diff: {_format_percent(alert.funding_rate_difference_percent)}"
        if alert.funding_rate_difference_percent is not None
        else None,
        f"Funding impact: {escape(alert.funding_impact)}",
        f"Next funding: {_format_datetime_utc(alert.next_funding_time)}"
        if alert.next_funding_time is not None
        else None,
        f"24h volume: {_format_usd(alert.volume_24h_usd)}"
        if alert.volume_24h_usd is not None
        else None,
        f"Timestamp: {_format_datetime_utc(alert.created_at)}",
    ]
    lines.extend(["", *[line for line in context_lines if line]])

    return "\n".join(lines)


def _exchange_link(exchange: str, symbol: str) -> str:
    label = escape(exchange)
    url = _exchange_trade_url(exchange, symbol)
    if url is None:
        return label

    return f'<a href="{escape(url, quote=True)}">{label}</a>'


def _exchange_trade_url(exchange: str, symbol: str) -> str | None:
    normalized_exchange = exchange.strip().lower()
    normalized_symbol = _trade_symbol(symbol)
    if not normalized_symbol:
        return None

    if normalized_exchange == "binance":
        return f"https://www.binance.com/en/futures/{quote(normalized_symbol)}"
    if normalized_exchange == "bybit":
        return f"https://www.bybit.com/trade/usdt/{quote(normalized_symbol)}"
    if normalized_exchange == "okx":
        okx_symbol = _okx_swap_symbol(normalized_symbol)
        if okx_symbol is None:
            return None
        return f"https://www.okx.com/trade-swap/{quote(okx_symbol.lower())}"

    return None


def _trade_symbol(symbol: str) -> str:
    return "".join(character for character in symbol.upper() if character.isalnum())


def _okx_swap_symbol(symbol: str) -> str | None:
    if not symbol.endswith("USDT") or len(symbol) <= 4:
        return None
    return f"{symbol[:-4]}-USDT-SWAP"


def _stable_alert_key(alert: AlertCandidate) -> str:
    return (
        alert.alert_key
        or f"{alert.symbol}:{alert.long_exchange}:{alert.short_exchange}"
    )


def _is_within_cooldown(
    last_sent_at: datetime | None,
    checked_at: datetime,
    cooldown_seconds: int,
) -> bool:
    if last_sent_at is None or cooldown_seconds <= 0:
        return False

    return (checked_at - last_sent_at).total_seconds() < cooldown_seconds


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


def _format_price(value: float) -> str:
    return f"{value:.8f}".rstrip("0").rstrip(".")


def _format_usd(value: float) -> str:
    if value >= 1:
        return f"${value:,.0f}"
    return f"${value:,.4f}".rstrip("0").rstrip(".")


def _format_datetime_utc(value: datetime) -> str:
    if value.tzinfo is None:
        return f"{value.strftime('%Y-%m-%d %H:%M')} UTC"
    return f"{value.astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M')} UTC"
