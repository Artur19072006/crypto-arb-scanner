from typing import Annotated

from fastapi import APIRouter, Query

from app.core.config import get_app_config
from app.domain.models import AppConfig, ArbitrageOpportunity, ScannerFilters
from app.services.mock_scanner import get_mock_opportunities

router = APIRouter()


@router.get("/health")
async def health_check() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/settings", response_model=AppConfig)
async def get_public_settings() -> AppConfig:
    return get_app_config()


@router.get("/opportunities", response_model=list[ArbitrageOpportunity])
async def list_opportunities(
    min_raw_spread: Annotated[float | None, Query(ge=0)] = None,
    min_net_spread: float | None = None,
    min_volume_24h_usd: Annotated[float | None, Query(ge=0)] = None,
    exchanges: Annotated[list[str] | None, Query()] = None,
) -> list[ArbitrageOpportunity]:
    default_filters = get_app_config().default_filters
    filters = ScannerFilters(
        min_raw_spread=(
            default_filters.min_raw_spread
            if min_raw_spread is None
            else min_raw_spread
        ),
        min_net_spread=(
            default_filters.min_net_spread
            if min_net_spread is None
            else min_net_spread
        ),
        min_volume_24h_usd=(
            default_filters.min_volume_24h_usd
            if min_volume_24h_usd is None
            else min_volume_24h_usd
        ),
        exchanges=(
            default_filters.exchanges
            if exchanges is None
            else _parse_exchanges(exchanges)
        ),
    )
    return await get_mock_opportunities(filters)


def _parse_exchanges(values: list[str] | None) -> tuple[str, ...]:
    if not values:
        return ()

    parsed: list[str] = []
    for value in values:
        parsed.extend(item.strip() for item in value.split(",") if item.strip())
    return tuple(dict.fromkeys(parsed))
