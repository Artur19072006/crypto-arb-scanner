import asyncio
import logging
from contextlib import suppress

from app.connectors.fake import FakeExchangeConnector
from app.core.config import get_app_config
from app.domain.models import ScannerFilters
from app.services.market_data_cache import MarketDataCache
from app.services.opportunity_store import OpportunityStore
from app.services.runtime import market_data_cache, opportunity_store
from app.services.spread_engine import calculate_opportunities


logger = logging.getLogger(__name__)
SCAN_INTERVAL_SECONDS = 5
DATA_SOURCE = "fake_connector"
SCANNER_MODE = "mock"


async def refresh_mock_scanner_once(
    cache: MarketDataCache = market_data_cache,
    store: OpportunityStore = opportunity_store,
) -> None:
    config = get_app_config()
    snapshots = await FakeExchangeConnector().get_snapshots()
    await cache.update_snapshots(snapshots)

    cached_snapshots = await cache.get_all_snapshots()
    enabled_exchange_filter = ScannerFilters(exchanges=config.default_filters.exchanges)
    opportunities = calculate_opportunities(
        cached_snapshots,
        config.fees,
        enabled_exchange_filter,
    )
    await store.update_opportunities(opportunities)


async def run_mock_scanner_loop(
    interval_seconds: int = SCAN_INTERVAL_SECONDS,
    cache: MarketDataCache = market_data_cache,
    store: OpportunityStore = opportunity_store,
) -> None:
    while True:
        try:
            await refresh_mock_scanner_once(cache, store)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Mock scanner refresh failed")

        await asyncio.sleep(interval_seconds)


async def stop_scanner_task(task: asyncio.Task[None]) -> None:
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task
