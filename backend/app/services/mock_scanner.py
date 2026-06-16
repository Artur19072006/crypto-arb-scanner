from app.connectors.fake import FakeExchangeConnector
from app.core.fees import DEFAULT_EXCHANGE_FEES
from app.domain.models import ArbitrageOpportunity, ScannerFilters
from app.services.spread_engine import calculate_opportunities


async def get_mock_opportunities(
    filters: ScannerFilters | None = None,
) -> list[ArbitrageOpportunity]:
    snapshots = await FakeExchangeConnector().get_snapshots()
    return calculate_opportunities(snapshots, DEFAULT_EXCHANGE_FEES, filters)
