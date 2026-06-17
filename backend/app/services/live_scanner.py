import asyncio
import logging
from contextlib import suppress

from app.connectors.registry import ConnectorRegistry, build_connector_registry_from_config
from app.core.config import get_app_config
from app.domain.models import AppConfig, ScannerFilters
from app.services.market_data_cache import MarketDataCache
from app.services.opportunity_store import OpportunityStore
from app.services.runtime import (
    alert_engine,
    market_data_cache,
    opportunity_store,
    symbol_universe_builder,
    telegram_notifier,
    websocket_market_data_manager,
)
from app.services.depth_check import apply_depth_checks
from app.services.spread_engine import calculate_opportunities
from app.services.websocket_market_data import WebSocketMarketDataManager


logger = logging.getLogger(__name__)
SCAN_INTERVAL_SECONDS = 5


def get_connector_registry(config: AppConfig | None = None) -> ConnectorRegistry:
    config = config or get_app_config()
    return build_connector_registry_from_config(config)


async def refresh_mock_scanner_once(
    cache: MarketDataCache = market_data_cache,
    store: OpportunityStore = opportunity_store,
    registry: ConnectorRegistry | None = None,
    websocket_manager: WebSocketMarketDataManager = websocket_market_data_manager,
    config: AppConfig | None = None,
) -> None:
    config = config or get_app_config()
    active_registry = registry or get_connector_registry(config)
    connectors = active_registry.list_connectors()
    if not connectors:
        await store.set_error("No active market data connectors")
        await alert_engine.clear_active()
        await websocket_manager.stop()
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

    await websocket_manager.ensure_started(
        scan_config,
        _websocket_symbols_by_connector(
            connectors,
            selected_symbols,
            selection.symbols_by_connector,
            scan_config.data_source_mode,
        ),
    )

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
        if not snapshots and not _websocket_market_data_enabled(scan_config):
            if scan_config.data_source_mode == "live":
                await store.update_opportunities([])
                await alert_engine.clear_active()
            return

    await cache.update_snapshots(snapshots, source="rest")

    cached_snapshots = await _snapshots_for_scan(cache, scan_config)
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
            active_alerts = await alert_engine.evaluate(
                opportunities,
                config.alerts,
                depth_check_enabled=config.depth_check.enabled,
            )
            await telegram_notifier.send_alerts(
                active_alerts,
                config.telegram,
                cooldown_seconds=config.alerts.cooldown_seconds,
            )
        else:
            await alert_engine.clear_active()
    except Exception as exc:
        errors.append(f"alerts: {exc}")

    if errors:
        await store.set_error("; ".join(errors))


def _is_mock_registry(registry: ConnectorRegistry) -> bool:
    return registry.list_names() == ("fake",)


def _websocket_market_data_enabled(config: AppConfig) -> bool:
    return (
        config.data_source_mode == "live"
        and config.market_data.mode == "websocket"
        and config.market_data.websocket.enabled
    )


async def _snapshots_for_scan(
    cache: MarketDataCache,
    config: AppConfig,
) -> list:
    if _websocket_market_data_enabled(config):
        return await cache.get_preferred_snapshots(
            preferred_source="websocket",
            stale_after_seconds=config.market_data.websocket.stale_after_seconds,
        )

    return await cache.get_all_snapshots()


def _websocket_symbols_by_connector(
    connectors: list,
    selected_symbols: tuple[str, ...] | None,
    symbols_by_connector: dict[str, tuple[str, ...]],
    data_source_mode: str,
) -> dict[str, tuple[str, ...]]:
    if data_source_mode != "live" or selected_symbols is None:
        return {}

    result: dict[str, tuple[str, ...]] = {}
    for connector in connectors:
        if symbols_by_connector:
            connector_symbols = symbols_by_connector.get(connector.name, ())
        else:
            connector_symbols = selected_symbols
        if connector_symbols:
            result[connector.name] = connector_symbols
    return result


async def run_mock_scanner_loop(
    interval_seconds: int = SCAN_INTERVAL_SECONDS,
    cache: MarketDataCache = market_data_cache,
    store: OpportunityStore = opportunity_store,
    registry: ConnectorRegistry | None = None,
    websocket_manager: WebSocketMarketDataManager = websocket_market_data_manager,
) -> None:
    active_registry = registry or get_connector_registry()
    try:
        while True:
            try:
                await refresh_mock_scanner_once(
                    cache=cache,
                    store=store,
                    registry=active_registry,
                    websocket_manager=websocket_manager,
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Mock scanner refresh failed")

            await asyncio.sleep(interval_seconds)
    finally:
        await websocket_manager.stop()


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
