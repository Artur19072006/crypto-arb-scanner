from app.connectors.fake import FakeExchangeConnector
from app.core.config import get_app_config
from app.domain.models import ArbitrageOpportunity, ScannerFilters
from app.services.spread_engine import calculate_opportunities


async def get_mock_opportunities(
    filters: ScannerFilters | None = None,
) -> list[ArbitrageOpportunity]:
    snapshots = await FakeExchangeConnector().fetch_snapshots()
    config = get_app_config()
    return calculate_opportunities(snapshots, config.fees, filters)
