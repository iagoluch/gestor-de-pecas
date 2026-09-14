from fastapi import APIRouter, Depends, Query

from backend.api.dependencies.auth import require_management_user
from backend.api.dependencies.facade import get_frontend_facade
from backend.api.dependencies.filters import PageParams, analytics_filter, pagination
from backend.api.schemas.auth import SessionUser
from mes.contracts import AnalyticsFilter


router = APIRouter(prefix="/traceability", tags=["Rastreabilidade"])


@router.get("/orders/{op}")
def trace_order(
    op: str,
    _user: SessionUser = Depends(require_management_user),
    facade=Depends(get_frontend_facade),
):
    return facade.rastreabilidade(op)


@router.get("/nestings")
def nestings(
    filters: AnalyticsFilter = Depends(analytics_filter),
    params: PageParams = Depends(pagination),
    search: str | None = Query(default=None, max_length=160),
    _user: SessionUser = Depends(require_management_user),
    facade=Depends(get_frontend_facade),
):
    payload = facade.nestings(filters)
    items = list(payload.get("items", []))
    if search:
        query = search.strip().casefold()
        items = [
            item for item in items
            if any(
                query in str(item.get(key) or "").casefold()
                for key in ("tarefa", "programa", "nesting", "maquina", "material", "status")
            )
        ]
    return {
        **{key: value for key, value in payload.items() if key not in {"items", "count"}},
        "items": params.slice(items),
        "page": params.meta(len(items)),
        "count": len(items),
    }

