from fastapi import APIRouter, Depends, Query
from fastapi import Path as ApiPath

from app.core.areas import trace_in_scope
from backend.api.dependencies.auth import require_management_user
from backend.api.dependencies.facade import get_frontend_facade
from backend.api.dependencies.filters import PageParams, analytics_filter, pagination
from backend.api.errors import AppError
from backend.api.schemas.auth import SessionUser
from mes.contracts import AnalyticsFilter
from mes.services.cut_utilization import resumir_aproveitamento


router = APIRouter(prefix="/traceability", tags=["Rastreabilidade"])


@router.get("/orders/{op}")
def trace_order(
    op: str = ApiPath(max_length=80),
    user: SessionUser = Depends(require_management_user),
    facade=Depends(get_frontend_facade),
):
    trace = facade.rastreabilidade(op)
    if not trace_in_scope(trace, user.sector_scope):
        raise AppError("trace_out_of_scope", "Essa OP não passou pelo seu setor.", status_code=403)
    return trace


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
    # Somas sobre TODOS os itens filtrados (não só a página): são o que os cartões da tela mostram.
    totals = {
        key: sum(float(item.get(key) or 0) for item in items)
        for key in ("previsto_segundos", "real_segundos", "real_periodo_segundos")
    }
    return {
        **{key: value for key, value in payload.items() if key not in {"items", "count"}},
        "totals": totals,
        # Aproveitamento da chapa sobre os mesmos itens filtrados dos totais.
        "aproveitamento": resumir_aproveitamento(items),
        "items": params.slice(items),
        "page": params.meta(len(items)),
        "count": len(items),
    }



@router.get("/inspection-waivers")
def inspection_waivers(
    filters: AnalyticsFilter = Depends(analytics_filter),
    params: PageParams = Depends(pagination),
    search: str | None = Query(default=None, max_length=160),
    _user: SessionUser = Depends(require_management_user),
    facade=Depends(get_frontend_facade),
):
    """Inspeções dispensadas no período (quem autorizou, motivo, crachá, quando)."""

    payload = facade.inspecoes_dispensadas(filters)
    items = list(payload.get("items", []))
    if search:
        query = search.strip().casefold()
        items = [
            item for item in items
            if any(
                query in str(item.get(key) or "").casefold()
                for key in ("op", "produto", "recurso", "motivo", "autorizado_por", "cracha")
            )
        ]
    return {
        **{key: value for key, value in payload.items() if key not in {"items", "count"}},
        "items": params.slice(items),
        "page": params.meta(len(items)),
        "count": len(items),
    }
