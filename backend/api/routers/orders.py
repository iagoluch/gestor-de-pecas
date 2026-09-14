from fastapi import APIRouter, Depends, Query

from backend.api.dependencies.auth import require_management_user
from backend.api.dependencies.facade import get_frontend_facade
from backend.api.dependencies.filters import PageParams, analytics_filter, pagination
from backend.api.schemas.auth import SessionUser
from mes.contracts import AnalyticsFilter


router = APIRouter(prefix="/orders", tags=["Produção"])


def _filter_items(items, *, status=None, search=None):
    result = list(items or [])
    if status:
        normalized = status.strip().casefold()
        result = [item for item in result if str(item.get("status") or "").casefold() == normalized]
    if search:
        query = search.strip().casefold()
        result = [
            item for item in result
            if any(
                query in str(item.get(key) or "").casefold()
                for key in ("op", "produto", "descricao", "operacao_atual", "recurso_real", "recurso_planejado")
            )
        ]
    return result


@router.get("")
def orders(
    filters: AnalyticsFilter = Depends(analytics_filter),
    params: PageParams = Depends(pagination),
    status: str | None = Query(default=None, max_length=80),
    search: str | None = Query(default=None, max_length=160),
    _user: SessionUser = Depends(require_management_user),
    facade=Depends(get_frontend_facade),
):
    payload = facade.ordens_producao(filters)
    items = _filter_items(payload.get("items", []), status=status, search=search)
    return {
        "periodo": payload.get("periodo"),
        "availability": "disponivel" if items else "sem_registros",
        "items": params.slice(items),
        "page": params.meta(len(items)),
    }


@router.get("/production")
def production(
    filters: AnalyticsFilter = Depends(analytics_filter),
    _user: SessionUser = Depends(require_management_user),
    facade=Depends(get_frontend_facade),
):
    return facade.producao_realizada(filters)


@router.get("/planned-vs-actual")
def planned_vs_actual(
    filters: AnalyticsFilter = Depends(analytics_filter),
    params: PageParams = Depends(pagination),
    _user: SessionUser = Depends(require_management_user),
    facade=Depends(get_frontend_facade),
):
    payload = facade.producao(filters)["planejado_x_realizado"]
    items = list(payload.get("items", []))
    return {
        **{key: value for key, value in payload.items() if key != "items"},
        "items": params.slice(items),
        "page": params.meta(len(items)),
    }

