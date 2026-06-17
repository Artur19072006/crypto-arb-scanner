from typing import Annotated, cast

from fastapi import APIRouter, HTTPException, Query

from app.core.config import get_app_config
from app.domain.models import (
    AlertHistoryResponse,
    AlertsResponse,
    AlertStatusResponse,
    AppConfig,
    ArbitrageOpportunity,
    OpportunitiesResponse,
    OpportunitySortBy,
    ScannerFilters,
    ScannerStatus,
    SortDirection,
    SpreadHistoryResponse,
    TelegramStatusResponse,
)
from app.services.live_scanner import active_connector_names, active_data_sources
from app.services.runtime import (
    alert_engine,
    market_data_cache,
    opportunity_store,
    spread_history_store,
    symbol_universe_builder,
    telegram_notifier,
    websocket_market_data_manager,
)
from app.services.symbols import normalize_symbol
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
    symbol_selection = await symbol_universe_builder.get_last_selection()
    selected_symbols = _status_symbols(config, symbol_selection.symbols)
    websocket_status = await websocket_market_data_manager.status()
    websocket_enabled = _websocket_market_data_enabled(config)
    stale_snapshot_count = (
        await market_data_cache.stale_snapshot_count(
            source="websocket",
            stale_after_seconds=config.market_data.websocket.stale_after_seconds,
        )
        if websocket_enabled
        else 0
    )
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
        market_data_mode=config.market_data.mode,
        websocket_enabled=websocket_enabled,
        websocket_active_exchanges=websocket_status.active_exchanges,
        websocket_connected=websocket_status.connected,
        websocket_connection_count=websocket_status.connection_count,
        websocket_chunk_count=websocket_status.chunk_count,
        websocket_symbol_count=websocket_status.symbol_count,
        websocket_last_message_at=websocket_status.last_message_at,
        websocket_last_error=websocket_status.last_error_by_exchange,
        websocket_reconnect_count=websocket_status.reconnect_count,
        stale_snapshot_count=stale_snapshot_count,
        last_websocket_update_at=(
            websocket_status.last_update_at
            or await market_data_cache.last_update_at("websocket")
        ),
        symbol_selection_mode=config.symbol_selection.mode,
        selected_symbol_count=len(selected_symbols),
        selected_symbols=selected_symbols[:20],
        symbol_selection_min_volume_24h_usd=(
            config.symbol_selection.min_volume_24h_usd
        ),
        symbol_selection_max_volume_24h_usd=(
            config.symbol_selection.max_volume_24h_usd
        ),
        symbols_on_2_exchanges=symbol_selection.symbols_on_2_exchanges,
        symbols_on_3_exchanges=symbol_selection.symbols_on_3_exchanges,
    )


@router.get("/alerts", response_model=AlertsResponse)
async def list_alerts() -> AlertsResponse:
    alerts = await alert_engine.get_active_alerts()
    return AlertsResponse(
        alerts=alerts,
        active_alert_count=len(alerts),
    )


@router.get("/alerts/history", response_model=AlertHistoryResponse)
async def list_alert_history(
    limit: Annotated[str | None, Query()] = None,
) -> AlertHistoryResponse:
    parsed_limit = _parse_alert_history_limit(limit)
    alerts = await alert_engine.get_history(parsed_limit)
    return AlertHistoryResponse(
        alerts=alerts,
        returned_count=len(alerts),
    )


@router.get("/alerts/status", response_model=AlertStatusResponse)
async def get_alert_status() -> AlertStatusResponse:
    config = get_app_config()
    return await alert_engine.get_status(config.alerts)


@router.get("/telegram/status", response_model=TelegramStatusResponse)
async def get_telegram_status() -> TelegramStatusResponse:
    config = get_app_config()
    return await telegram_notifier.get_status(config.telegram)


DEFAULT_OPPORTUNITY_LIMIT = 100
MAX_OPPORTUNITY_LIMIT = 500
DEFAULT_ALERT_HISTORY_LIMIT = 50
MAX_ALERT_HISTORY_LIMIT = 200
DEFAULT_SPREAD_HISTORY_LIMIT = 500
MAX_SPREAD_HISTORY_LIMIT = 5000


@router.get("/opportunities", response_model=OpportunitiesResponse)
async def list_opportunities(
    min_raw_spread: Annotated[str | None, Query()] = None,
    min_net_spread: Annotated[str | None, Query()] = None,
    min_volume_24h_usd: Annotated[str | None, Query()] = None,
    exchanges: Annotated[list[str] | None, Query()] = None,
    symbol_query: Annotated[str | None, Query()] = None,
    sort_by: Annotated[str | None, Query()] = None,
    sort_dir: Annotated[str | None, Query()] = None,
    limit: Annotated[str | None, Query()] = None,
) -> OpportunitiesResponse:
    config = get_app_config()
    stored_opportunities = await opportunity_store.get_all_opportunities()
    opportunities = stored_opportunities
    if config.data_source_mode == "live":
        opportunities = await _filter_live_selected_symbols(opportunities)

    filters = _build_filters(
        min_raw_spread=min_raw_spread,
        min_net_spread=min_net_spread,
        min_volume_24h_usd=min_volume_24h_usd,
        exchanges=exchanges,
    )
    return _build_opportunities_response(
        stored_opportunities=stored_opportunities,
        queryable_opportunities=opportunities,
        filters=filters,
        symbol_query=symbol_query,
        sort_by=sort_by,
        sort_dir=sort_dir,
        limit=limit,
    )


@router.get("/spread-history", response_model=SpreadHistoryResponse)
async def get_spread_history(
    symbol: Annotated[str, Query()],
    long_exchange: Annotated[str, Query()],
    short_exchange: Annotated[str, Query()],
    limit: Annotated[str | None, Query()] = None,
) -> SpreadHistoryResponse:
    parsed_limit = _parse_spread_history_limit(limit)
    normalized_symbol = normalize_symbol(symbol)
    if not normalized_symbol:
        raise HTTPException(status_code=422, detail="symbol is required")

    parsed_long_exchange = _parse_required_text(long_exchange, "long_exchange")
    parsed_short_exchange = _parse_required_text(short_exchange, "short_exchange")
    config = get_app_config()
    rows = await spread_history_store.get_history(
        config.history.sqlite_path,
        normalized_symbol,
        parsed_long_exchange,
        parsed_short_exchange,
        parsed_limit,
    )

    return SpreadHistoryResponse(
        symbol=rows[0].symbol if rows else normalized_symbol,
        long_exchange=rows[0].long_exchange if rows else parsed_long_exchange,
        short_exchange=rows[0].short_exchange if rows else parsed_short_exchange,
        limit=parsed_limit,
        returned_count=len(rows),
        rows=rows,
    )


def _build_opportunities_response(
    stored_opportunities: list[ArbitrageOpportunity],
    queryable_opportunities: list[ArbitrageOpportunity],
    filters: ScannerFilters,
    symbol_query: str | None = None,
    sort_by: str | None = None,
    sort_dir: str | None = None,
    limit: str | int | None = None,
) -> OpportunitiesResponse:
    filtered = filter_opportunities(queryable_opportunities, filters)
    filtered = _filter_by_symbol_query(filtered, symbol_query)
    parsed_sort_by = _parse_sort_by(sort_by)
    parsed_sort_dir = _parse_sort_dir(sort_dir)
    parsed_limit = _parse_limit(limit)
    sorted_opportunities = _sort_opportunities(
        filtered,
        sort_by=parsed_sort_by,
        sort_dir=parsed_sort_dir,
    )
    returned = sorted_opportunities[:parsed_limit]

    return OpportunitiesResponse(
        opportunities=returned,
        total_stored_opportunity_count=len(stored_opportunities),
        filtered_opportunity_count=len(filtered),
        returned_count=len(returned),
        sort_by=parsed_sort_by,
        sort_dir=parsed_sort_dir,
        limit=parsed_limit,
    )


async def _filter_live_selected_symbols(
    opportunities: list[ArbitrageOpportunity],
) -> list[ArbitrageOpportunity]:
    selection = await symbol_universe_builder.get_last_selection()
    allowed_symbols = set(selection.symbols)
    if not allowed_symbols:
        return []

    return [
        opportunity
        for opportunity in opportunities
        if normalize_symbol(opportunity.symbol) in allowed_symbols
    ]


def _status_symbols(
    config: AppConfig,
    selected_symbols: tuple[str, ...],
) -> tuple[str, ...]:
    if selected_symbols:
        return selected_symbols
    if config.data_source_mode == "mock" or config.symbol_selection.mode == "manual":
        return tuple(
            dict.fromkeys(
                symbol
                for symbol in (
                    normalize_symbol(raw_symbol)
                    for raw_symbol in config.symbol_allowlist[:config.max_symbols]
                )
                if symbol
            )
        )
    return ()


def _websocket_market_data_enabled(config: AppConfig) -> bool:
    return (
        config.data_source_mode == "live"
        and config.market_data.mode == "websocket"
        and config.market_data.websocket.enabled
    )


def _filter_by_symbol_query(
    opportunities: list[ArbitrageOpportunity],
    symbol_query: str | None,
) -> list[ArbitrageOpportunity]:
    normalized_query = normalize_symbol(symbol_query or "")
    if not normalized_query:
        return opportunities

    return [
        opportunity
        for opportunity in opportunities
        if normalized_query in normalize_symbol(opportunity.symbol)
    ]


def _sort_opportunities(
    opportunities: list[ArbitrageOpportunity],
    sort_by: OpportunitySortBy,
    sort_dir: SortDirection,
) -> list[ArbitrageOpportunity]:
    reverse = sort_dir == "desc"
    if sort_by == "symbol":
        return sorted(
            opportunities,
            key=lambda opportunity: opportunity.symbol,
            reverse=reverse,
        )

    return sorted(
        opportunities,
        key=lambda opportunity: _sort_value(opportunity, sort_by),
        reverse=reverse,
    )


def _sort_value(
    opportunity: ArbitrageOpportunity,
    sort_by: OpportunitySortBy,
) -> float:
    if sort_by == "raw_spread":
        return opportunity.raw_spread_percent
    if sort_by == "volume_24h":
        return opportunity.volume_24h_usd
    if sort_by == "updated_at":
        return opportunity.timestamp.timestamp()
    return opportunity.estimated_net_spread_percent


def _parse_sort_by(value: str | None) -> OpportunitySortBy:
    normalized = (value or "net_spread").strip().lower()
    allowed: set[OpportunitySortBy] = {
        "raw_spread",
        "net_spread",
        "volume_24h",
        "symbol",
        "updated_at",
    }
    if normalized in allowed:
        return cast(OpportunitySortBy, normalized)

    raise HTTPException(
        status_code=422,
        detail="sort_by must be one of raw_spread, net_spread, volume_24h, symbol, updated_at",
    )


def _parse_sort_dir(value: str | None) -> SortDirection:
    normalized = (value or "desc").strip().lower()
    if normalized in {"asc", "desc"}:
        return cast(SortDirection, normalized)

    raise HTTPException(
        status_code=422,
        detail="sort_dir must be asc or desc",
    )


def _parse_limit(value: str | int | None) -> int:
    if value in (None, ""):
        return DEFAULT_OPPORTUNITY_LIMIT

    try:
        parsed = int(str(value).strip())
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail="limit must be an integer",
        ) from exc

    if parsed < 1:
        raise HTTPException(
            status_code=422,
            detail="limit must be at least 1",
        )
    if parsed > MAX_OPPORTUNITY_LIMIT:
        raise HTTPException(
            status_code=422,
            detail=f"limit must be at most {MAX_OPPORTUNITY_LIMIT}",
        )

    return parsed


def _parse_alert_history_limit(value: str | int | None) -> int:
    if value in (None, ""):
        return DEFAULT_ALERT_HISTORY_LIMIT

    try:
        parsed = int(str(value).strip())
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail="limit must be an integer",
        ) from exc

    if parsed < 1:
        raise HTTPException(
            status_code=422,
            detail="limit must be at least 1",
        )
    if parsed > MAX_ALERT_HISTORY_LIMIT:
        raise HTTPException(
            status_code=422,
            detail=f"limit must be at most {MAX_ALERT_HISTORY_LIMIT}",
        )

    return parsed


def _parse_spread_history_limit(value: str | int | None) -> int:
    if value in (None, ""):
        return DEFAULT_SPREAD_HISTORY_LIMIT

    try:
        parsed = int(str(value).strip())
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail="limit must be an integer",
        ) from exc

    if parsed < 1:
        raise HTTPException(
            status_code=422,
            detail="limit must be at least 1",
        )
    if parsed > MAX_SPREAD_HISTORY_LIMIT:
        raise HTTPException(
            status_code=422,
            detail=f"limit must be at most {MAX_SPREAD_HISTORY_LIMIT}",
        )

    return parsed


def _parse_required_text(value: str, field_name: str) -> str:
    parsed = value.strip()
    if not parsed:
        raise HTTPException(status_code=422, detail=f"{field_name} is required")
    return parsed


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
