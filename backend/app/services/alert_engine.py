import asyncio
from datetime import datetime, timezone

from app.domain.models import (
    AlertCandidate,
    AlertConfig,
    AlertEvent,
    AlertSeverity,
    AlertStatusResponse,
    ArbitrageOpportunity,
    DepthStatus,
)


class AlertEngine:
    def __init__(self, history_limit: int = 100) -> None:
        self.history_limit = history_limit
        self._active_alerts: list[AlertCandidate] = []
        self._history: list[AlertEvent] = []
        self._last_alert_by_key: dict[str, datetime] = {}
        self._suppressed_count = 0
        self._last_evaluated_at: datetime | None = None
        self._lock = asyncio.Lock()

    async def evaluate(
        self,
        opportunities: list[ArbitrageOpportunity],
        config: AlertConfig,
        depth_check_enabled: bool,
        evaluated_at: datetime | None = None,
    ) -> list[AlertCandidate]:
        now = evaluated_at or datetime.now(timezone.utc)
        if not config.enabled:
            await self.clear_active()
            return []

        async with self._lock:
            candidates = [
                self._candidate_from_opportunity(
                    opportunity,
                    config=config,
                    depth_check_enabled=depth_check_enabled,
                    created_at=now,
                )
                for opportunity in opportunities
            ]
            active_candidates = sorted(
                (
                    candidate
                    for candidate in candidates
                    if not candidate.suppressed
                ),
                key=lambda candidate: candidate.alert_score,
                reverse=True,
            )
            selected_alerts = active_candidates[:config.max_alerts_per_scan]
            overflow_alerts = [
                _suppress_candidate(
                    candidate,
                    "Suppressed because max alerts per scan reached",
                )
                for candidate in active_candidates[config.max_alerts_per_scan:]
            ]
            suppressed_candidates = [
                candidate for candidate in candidates if candidate.suppressed
            ]
            all_candidates = [
                *selected_alerts,
                *overflow_alerts,
                *suppressed_candidates,
            ]

            for candidate in selected_alerts:
                self._last_alert_by_key[_alert_key(candidate)] = now

            self._active_alerts = selected_alerts
            self._suppressed_count = sum(
                1 for candidate in all_candidates if candidate.suppressed
            )
            self._last_evaluated_at = now
            self._history.extend(
                AlertEvent(**candidate.model_dump())
                for candidate in all_candidates
            )
            self._history = self._history[-self.history_limit:]
            return list(self._active_alerts)

    async def clear_active(self) -> None:
        async with self._lock:
            self._active_alerts = []
            self._suppressed_count = 0

    async def get_active_alerts(self) -> list[AlertCandidate]:
        async with self._lock:
            return list(self._active_alerts)

    async def get_history(self, limit: int = 50) -> list[AlertEvent]:
        async with self._lock:
            return list(reversed(self._history[-limit:]))

    async def get_status(self, config: AlertConfig) -> AlertStatusResponse:
        async with self._lock:
            return AlertStatusResponse(
                enabled=config.enabled,
                cooldown_seconds=config.cooldown_seconds,
                active_alert_count=len(self._active_alerts),
                suppressed_count=self._suppressed_count,
                last_evaluated_at=self._last_evaluated_at,
            )

    def _candidate_from_opportunity(
        self,
        opportunity: ArbitrageOpportunity,
        config: AlertConfig,
        depth_check_enabled: bool,
        created_at: datetime,
    ) -> AlertCandidate:
        depth = opportunity.depth_check
        depth_status = depth.depth_status if depth else None
        depth_adjusted_net = (
            depth.depth_adjusted_net_spread_percent
            if depth
            else None
        )
        effective_net_spread = (
            depth_adjusted_net
            if depth_adjusted_net is not None
            else opportunity.estimated_net_spread_percent
        )
        active_threshold = (
            config.min_depth_adjusted_net_spread_percent
            if depth_adjusted_net is not None
            else config.min_net_spread_percent
        )
        reasons: list[str] = []
        suppression_reason = _base_suppression_reason(
            opportunity=opportunity,
            depth_status=depth_status,
            effective_net_spread=effective_net_spread,
            active_threshold=active_threshold,
            config=config,
            depth_check_enabled=depth_check_enabled,
        )

        if effective_net_spread >= active_threshold:
            reasons.append("Net spread above alert threshold")
        else:
            reasons.append("Suppressed because net spread below threshold")

        if depth_adjusted_net is not None and depth_adjusted_net > 0:
            reasons.append("Depth-adjusted spread remains positive")

        reasons.extend(_depth_reasons(depth_status, depth_check_enabled))
        reasons.extend(_funding_reasons(opportunity, effective_net_spread, active_threshold))
        reasons.extend(_liquidity_reasons(opportunity))
        reasons.extend(_slippage_reasons(opportunity, config))

        if suppression_reason is None:
            suppression_reason = _cooldown_suppression_reason(
                opportunity=opportunity,
                config=config,
                created_at=created_at,
                last_alert_at=self._last_alert_by_key.get(
                    _opportunity_key(opportunity)
                ),
            )
            if suppression_reason:
                reasons.append(suppression_reason)

        alert_score = _alert_score(
            opportunity=opportunity,
            effective_net_spread=effective_net_spread,
            depth_adjusted_net=depth_adjusted_net,
            depth_status=depth_status,
            config=config,
        )
        severity = _severity(
            effective_net_spread=effective_net_spread,
            threshold=active_threshold,
            alert_score=alert_score,
            suppressed=suppression_reason is not None,
        )

        return AlertCandidate(
            id=_alert_id(opportunity, created_at),
            alert_key=_opportunity_key(opportunity),
            symbol=opportunity.symbol,
            long_exchange=opportunity.long_exchange,
            short_exchange=opportunity.short_exchange,
            raw_spread_percent=opportunity.raw_spread_percent,
            estimated_net_spread_percent=opportunity.estimated_net_spread_percent,
            depth_adjusted_net_spread_percent=depth_adjusted_net,
            depth_status=depth_status,
            target_notional_usd=depth.target_notional_usd if depth else None,
            long_slippage_percent=depth.long_slippage_percent if depth else None,
            short_slippage_percent=depth.short_slippage_percent if depth else None,
            funding_impact=opportunity.funding_impact,
            liquidity_status=opportunity.liquidity_status,
            alert_score=round(alert_score, 4),
            severity=severity,
            reasons=reasons,
            created_at=created_at,
            suppressed=suppression_reason is not None,
            suppression_reason=suppression_reason,
        )


def _base_suppression_reason(
    opportunity: ArbitrageOpportunity,
    depth_status: DepthStatus | None,
    effective_net_spread: float,
    active_threshold: float,
    config: AlertConfig,
    depth_check_enabled: bool,
) -> str | None:
    if opportunity.volume_24h_usd < config.min_volume_24h_usd:
        return "Suppressed because volume below threshold"
    if effective_net_spread < active_threshold:
        return "Suppressed because net spread below threshold"
    if depth_check_enabled and depth_status is None:
        return "Suppressed because depth status Unknown"
    if depth_status == "Insufficient":
        return "Suppressed because depth is insufficient"
    if depth_status == "Unknown" and depth_check_enabled:
        return "Suppressed because depth status Unknown"
    if (
        depth_status is not None
        and depth_status not in config.require_depth_status
        and not (depth_status == "Unknown" and not depth_check_enabled)
    ):
        return f"Suppressed because depth status {depth_status} is not allowed"
    if (
        opportunity.funding_impact == "Bad"
        and effective_net_spread < active_threshold * 2
    ):
        return "Suppressed because funding impact is bad for weak spread"
    return None


def _cooldown_suppression_reason(
    opportunity: ArbitrageOpportunity,
    config: AlertConfig,
    created_at: datetime,
    last_alert_at: datetime | None,
) -> str | None:
    if last_alert_at is None or config.cooldown_seconds <= 0:
        return None

    elapsed_seconds = (created_at - last_alert_at).total_seconds()
    if elapsed_seconds < config.cooldown_seconds:
        return "Suppressed by cooldown"
    return None


def _alert_score(
    opportunity: ArbitrageOpportunity,
    effective_net_spread: float,
    depth_adjusted_net: float | None,
    depth_status: DepthStatus | None,
    config: AlertConfig,
) -> float:
    score = effective_net_spread * 10
    if depth_adjusted_net is not None:
        score += 5 if depth_adjusted_net > 0 else -5

    if depth_status == "OK":
        score += 3
    elif depth_status == "Thin":
        score += 1
    elif depth_status == "Unknown":
        score -= 2
    elif depth_status == "Insufficient":
        score -= 100

    if opportunity.funding_impact == "Good":
        score += 1
    elif opportunity.funding_impact == "Bad":
        score -= 2

    if opportunity.liquidity_status == "OK":
        score += 1
    elif opportunity.liquidity_status == "Holey":
        score -= 2

    depth = opportunity.depth_check
    if depth:
        slippages = (
            depth.long_slippage_percent,
            depth.short_slippage_percent,
        )
        for slippage in slippages:
            if slippage is not None and slippage > config.max_allowed_slippage_percent:
                score -= 1

    return score


def _severity(
    effective_net_spread: float,
    threshold: float,
    alert_score: float,
    suppressed: bool,
) -> AlertSeverity:
    if suppressed:
        return "Info"
    if effective_net_spread >= max(threshold * 3, 0.5) or alert_score >= 10:
        return "Strong"
    if effective_net_spread >= threshold:
        return "Watch"
    return "Info"


def _depth_reasons(
    depth_status: DepthStatus | None,
    depth_check_enabled: bool,
) -> list[str]:
    if depth_status == "OK":
        return ["Depth status OK for target size"]
    if depth_status == "Thin":
        return ["Depth status Thin for target size"]
    if depth_status == "Insufficient":
        return ["Suppressed because depth is insufficient"]
    if depth_status == "Unknown" or (depth_status is None and depth_check_enabled):
        return ["Suppressed because depth status Unknown"]
    return []


def _funding_reasons(
    opportunity: ArbitrageOpportunity,
    effective_net_spread: float,
    active_threshold: float,
) -> list[str]:
    if opportunity.funding_impact == "Good":
        return ["Funding impact Good"]
    if opportunity.funding_impact != "Bad":
        return []
    if effective_net_spread < active_threshold * 2:
        return ["Suppressed because funding impact is bad for weak spread"]
    return ["Funding impact Bad lowers score"]


def _liquidity_reasons(opportunity: ArbitrageOpportunity) -> list[str]:
    if opportunity.liquidity_status == "Holey":
        return ["Liquidity status Holey lowers score"]
    return []


def _slippage_reasons(
    opportunity: ArbitrageOpportunity,
    config: AlertConfig,
) -> list[str]:
    depth = opportunity.depth_check
    if depth is None:
        return []

    reasons = []
    if (
        depth.long_slippage_percent is not None
        and depth.long_slippage_percent > config.max_allowed_slippage_percent
    ):
        reasons.append("Long slippage above alert preference")
    if (
        depth.short_slippage_percent is not None
        and depth.short_slippage_percent > config.max_allowed_slippage_percent
    ):
        reasons.append("Short slippage above alert preference")
    return reasons


def _suppress_candidate(
    candidate: AlertCandidate,
    reason: str,
) -> AlertCandidate:
    reasons = list(candidate.reasons)
    if reason not in reasons:
        reasons.append(reason)
    return candidate.model_copy(
        update={
            "suppressed": True,
            "suppression_reason": reason,
            "severity": "Info",
            "reasons": reasons,
        }
    )


def _alert_id(opportunity: ArbitrageOpportunity, created_at: datetime) -> str:
    return f"{_opportunity_key(opportunity)}:{int(created_at.timestamp())}"


def _alert_key(candidate: AlertCandidate) -> str:
    return candidate.alert_key


def _opportunity_key(opportunity: ArbitrageOpportunity) -> str:
    return f"{opportunity.symbol}:{opportunity.long_exchange}:{opportunity.short_exchange}"
