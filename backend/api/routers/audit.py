from fastapi import APIRouter, Depends

from backend.api.dependencies.auth import require_management_user
from backend.api.dependencies.facade import get_frontend_facade
from backend.api.dependencies.filters import PageParams, analytics_filter, pagination
from backend.api.schemas.auth import SessionUser
from mes.contracts import AnalyticsFilter


router = APIRouter(prefix="/audit", tags=["Auditoria"])


@router.get("/appointments")
def appointments(
    filters: AnalyticsFilter = Depends(analytics_filter),
    params: PageParams = Depends(pagination),
    _user: SessionUser = Depends(require_management_user),
    facade=Depends(get_frontend_facade),
):
    payload = facade.ordens_producao(filters)
    items = list(payload.get("items", []))
    return {
        "periodo": payload.get("periodo"),
        "availability": payload.get("availability"),
        "items": params.slice(items),
        "page": params.meta(len(items)),
    }


@router.get("")
def audit(
    filters: AnalyticsFilter = Depends(analytics_filter),
    params: PageParams = Depends(pagination),
    _user: SessionUser = Depends(require_management_user),
    facade=Depends(get_frontend_facade),
):
    payload = facade.auditoria(filters)
    issues = list(payload.get("issues", []))
    return {
        **{key: value for key, value in payload.items() if key != "issues"},
        "issues": params.slice(issues),
        "page": params.meta(len(issues)),
    }


@router.get("/reliability")
def reliability(
    filters: AnalyticsFilter = Depends(analytics_filter),
    _user: SessionUser = Depends(require_management_user),
    facade=Depends(get_frontend_facade),
):
    payload = facade.auditoria(filters)
    return {
        "periodo": payload.get("periodo"),
        "records_analyzed": payload.get("records_analyzed"),
        "resource_states_analyzed": payload.get("resource_states_analyzed"),
        "rateio_sessions_analyzed": payload.get("rateio_sessions_analyzed"),
        "by_severity": payload.get("by_severity"),
        "reliability_percentage": payload.get("reliability_percentage"),
        "reliability_reason": payload.get("reliability_reason"),
        "physical_state_source": payload.get("physical_state_source"),
    }
