"""Endpoint somente leitura do Andon Geral."""

from fastapi import APIRouter, Depends

from backend.api.dependencies.auth import require_andon_user
from backend.api.dependencies.facade import get_frontend_facade
from backend.api.dependencies.filters import analytics_filter
from backend.api.schemas.auth import SessionUser
from mes.contracts import AnalyticsFilter


router = APIRouter(prefix="/andon", tags=["Andon"])


@router.get("")
def snapshot(
    filters: AnalyticsFilter = Depends(analytics_filter),
    _user: SessionUser = Depends(require_andon_user),
    facade=Depends(get_frontend_facade),
):
    return facade.andon(filters)
