import asyncio
import logging
from contextlib import suppress

from app.connectors.registry import ConnectorRegistry, build_connector_registry_from_config
from app.core.config import get_app_config
from app.domain.models import ScannerFilters
from app.services.market_data_cache import MarketDataCache
from app.services.opportunity_store import OpportunityStore
from app.services.runtime import (
    alert_engine,
    market_data_cache,
    opportunity_store,
    symbol_universe_builder,
)
from app.services.depth_check import apply_depth_checks
from app.services.spread_engine import calculate_opportunities


logger = logging.getLogger(__name__)
SCAN_INTERVAL_SECONDS = 5
def get_connector_registry() -> ConnectorRegistry:
    config = get_app_config()
    return build_connector_registry_from_config(config)


async def refresh_mock_scanner_once(
    cache: MarketDataCache = market_data_cache,
    store: OpportunityStore = opportunity_store,
    registry: ConnectorRegistry | None = None,
) -> None:
    config = get_app_config()
    active_registry = registry or get_connector_registry()
    connectors = active_registry.list_connectors()
    if not connectors:
        await store.set_error("No active market data connectors")
        await alert_engine.clear_active()
        return

    scan_config = (
        config.model_copy(update={"data_source_mode": "mock"})
        if _is_mock_registry(active_registry)
        else config
    )
    selected_symbols: tuple[str, ...] | None = None
    selection = await symbol_universe_builder.build(scan_config, active_registry)
    errors: list[str] = list(selection.errors)
    if scan_config.data_source_mode == "live":
        selected_symbols = selection.symbols
        if not selected_symbols and not errors:
            errors.append("No symbols selected for live scanning")

    snapshots = []
    for connector in connectors:
        connector_symbols = selected_symbols
        if (
            scan_config.data_source_mode == "live"
            and selection.symbols_by_connector
        ):
            connector_symbols = selection.symbols_by_connector.get(connector.name, ())
            if not connector_symbols:
                continue

        try:
            snapshots.extend(await connector.fetch_snapshots(connector_symbols))
        except Exception as exc:
            errors.append(f"{connector.name}: {exc}")

    if errors:
        await store.set_error("; ".join(errors))
        if not snapshots:
            if scan_config.data_source_mode == "live":
                await store.update_opportunities([])
                await alert_engine.clear_active()
            return

    await cache.update_snapshots(snapshots)

    cached_snapshots = await cache.get_all_snapshots()
    if scan_config.data_source_mode == "live" and selected_symbols is not None:
        allowed_symbols = set(selected_symbols)
        cached_snapshots = [
            snapshot
            for snapshot in cached_snapshots
            if snapshot.symbol in allowed_symbols
        ]

    enabled_exchange_filter = ScannerFilters(exchanges=config.default_filters.exchanges)
    opportunities = calculate_opportunities(
        cached_snapshots,
        config.fees,
        enabled_exchange_filter,
    )
    try:
        opportunities = await apply_depth_checks(
            opportunities,
            connectors,
            config.depth_check,
        )
    except Exception as exc:
        errors.append(f"depth_check: {exc}")

    await store.update_opportunities(opportunities)
    try:
        if config.alerts.enabled:
            await alert_engine.evaluate(
                opportunities,
                config.alerts,
                depth_check_enabled=config.depth_check.enabled,
            )
        else:
            await alert_engine.clear_active()
    except Exception as exc:
        errors.append(f"alerts: {exc}")

    if errors:
        await store.set_error("; ".join(errors))


def _is_mock_registry(registry: ConnectorRegistry) -> bool:
    return registry.list_names() == ("fake",)


async def run_mock_scanner_loop(
    interval_seconds: int = SCAN_INTERVAL_SECONDS,
    cache: MarketDataCache = market_data_cache,
    store: OpportunityStore = opportunity_store,
    registry: ConnectorRegistry | None = None,
) -> None:
    active_registry = registry or get_connector_registry()
    while True:
        try:
            await refresh_mock_scanner_once(cache, store, active_registry)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Mock scanner refresh failed")

        await asyncio.sleep(interval_seconds)


async def stop_scanner_task(task: asyncio.Task[None]) -> None:
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task


def active_connector_names() -> tuple[str, ...]:
    return get_connector_registry().list_names()


def active_data_sources() -> tuple[str, ...]:
    return tuple(
        connector.data_source
        for connector in get_connector_registry().list_connectors()
    )
