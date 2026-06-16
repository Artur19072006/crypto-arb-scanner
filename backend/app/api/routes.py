from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from app.core.config import get_app_config
from app.domain.models import (
    AppConfig,
    ArbitrageOpportunity,
    ScannerFilters,
    ScannerStatus,
)
from app.services.live_scanner import active_connector_names, active_data_sources
from app.services.runtime import market_data_cache, opportunity_store
from app.services.spread_engine import filter_opportunities

router = APIRouter()


@router.get("/health")
async def health_check() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/settings", response_model=AppConfig)
async def get_public_settings() -> AppConfig:
    return get_app_config()


@router.get("/status", response_model=ScannerStatus)
async def get_scanner_status() -> ScannerStatus:
    config = get_app_config()
    data_sources = active_data_sources()
    last_error = await opportunity_store.get_last_error()
    stored_opportunity_count = await opportunity_store.opportunity_count()
    return ScannerStatus(
        data_source=", ".join(data_sources) if data_sources else "none",
        data_source_mode=config.data_source_mode,
        mode=config.data_source_mode,
        scanner_health="degraded" if last_error else "ok",
        last_error=last_error,
        last_updated=await opportunity_store.get_last_updated(),
        snapshot_count=await market_data_cache.snapshot_count(),
        opportunity_count=stored_opportunity_count,
        total_opportunity_count=stored_opportunity_count,
        stored_opportunity_count=stored_opportunity_count,
        enabled_exchanges=config.default_filters.exchanges,
        active_connectors=active_connector_names(),
    )


@router.get("/opportunities", response_model=list[ArbitrageOpportunity])
async def list_opportunities(
    min_raw_spread: Annotated[str | None, Query()] = None,
    min_net_spread: Annotated[str | None, Query()] = None,
    min_volume_24h_usd: Annotated[str | None, Query()] = None,
    exchanges: Annotated[list[str] | None, Query()] = None,
) -> list[ArbitrageOpportunity]:
    opportunities = await opportunity_store.get_all_opportunities()
    return filter_opportunities(opportunities, _build_filters(
        min_raw_spread=min_raw_spread,
        min_net_spread=min_net_spread,
        min_volume_24h_usd=min_volume_24h_usd,
        exchanges=exchanges,
    ))


def _build_filters(
    min_raw_spread: str | float | None = None,
    min_net_spread: str | float | None = None,
    min_volume_24h_usd: str | float | None = None,
    exchanges: list[str] | None = None,
) -> ScannerFilters:
    default_filters = get_app_config().default_filters
    parsed_min_raw_spread = _parse_optional_decimal_filter(
        min_raw_spread,
        "min_raw_spread",
        min_value=0,
    )
    parsed_min_net_spread = _parse_optional_decimal_filter(
        min_net_spread,
        "min_net_spread",
    )
    parsed_min_volume_24h_usd = _parse_optional_decimal_filter(
        min_volume_24h_usd,
        "min_volume_24h_usd",
        min_value=0,
    )

    return ScannerFilters(
        min_raw_spread=(
            default_filters.min_raw_spread
            if parsed_min_raw_spread is None
            else parsed_min_raw_spread
        ),
        min_net_spread=(
            default_filters.min_net_spread
            if parsed_min_net_spread is None
            else parsed_min_net_spread
        ),
        min_volume_24h_usd=(
            default_filters.min_volume_24h_usd
            if parsed_min_volume_24h_usd is None
            else parsed_min_volume_24h_usd
        ),
        exchanges=(
            default_filters.exchanges
            if exchanges is None
            else _parse_exchanges(exchanges)
        ),
    )


def _parse_exchanges(values: list[str] | None) -> tuple[str, ...]:
    if not values:
        return ()

    parsed: list[str] = []
    for value in values:
        parsed.extend(item.strip() for item in value.split(",") if item.strip())
    return tuple(dict.fromkeys(parsed))


def _parse_optional_decimal_filter(
    value: str | float | int | None,
    field_name: str,
    min_value: float | None = None,
) -> float | None:
    if value is None or value == "":
        return None

    normalized = str(value).strip().replace(",", ".")
    if not normalized:
        return None

    try:
        parsed = float(normalized)
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"{field_name} must be a number",
        ) from exc

    if min_value is not None and parsed < min_value:
        raise HTTPException(
            status_code=422,
            detail=f"{field_name} must be at least {min_value}",
        )

    return parsed
