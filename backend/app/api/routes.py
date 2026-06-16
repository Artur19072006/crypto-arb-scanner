from fastapi import APIRouter

from app.models.opportunity import Opportunity
from app.services.mock_scanner import get_mock_opportunities

router = APIRouter()


@router.get("/health")
async def health_check() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/opportunities", response_model=list[Opportunity])
async def list_opportunities() -> list[Opportunity]:
    return await get_mock_opportunities()
