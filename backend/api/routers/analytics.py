from datetime import datetime

from fastapi import APIRouter, Depends, Request

from backend.api.database import get_database
from backend.api.dependencies.bulkhead import management_read_slot
from backend.api.dependencies.clock import request_now_func
from backend.api.dependencies.auth import require_management_user
from backend.api.dependencies.facade import get_frontend_facade
from backend.api.dependencies.filters import analytics_filter
from backend.api.errors import AppError
from backend.api.schemas.auth import SessionUser
from mes.contracts import AnalyticsFilter
from mes.services.person_hours import horas_por_pessoa


router = APIRouter(prefix="/analytics", tags=["Análises"], dependencies=[Depends(management_read_slot)])


@router.get("")
def all_analytics(
    filters: AnalyticsFilter = Depends(analytics_filter),
    _user: SessionUser = Depends(require_management_user),
    facade=Depends(get_frontend_facade),
):
    return facade.analises(filters)


@router.get("/people-hours")
def people_hours(
    request: Request,
    filters: AnalyticsFilter = Depends(analytics_filter),
    _user: SessionUser = Depends(require_management_user),
    database=Depends(get_database),
):
    rows = database.listar_participacoes_operador_periodo(
        filters.inicio, filters.fim, recurso=filters.recurso, setor=filters.setor,
        op=filters.op, cracha=filters.operador,
    )
    now_func = request_now_func(request)
    return horas_por_pessoa(rows, filters.inicio, filters.fim, now_func() if now_func else datetime.now())


@router.get("/{analysis_type}")
def analysis(
    analysis_type: str,
    filters: AnalyticsFilter = Depends(analytics_filter),
    _user: SessionUser = Depends(require_management_user),
    facade=Depends(get_frontend_facade),
):
    aliases = {
        "oee": "oee",
        "hours-utilization": "tempos",
        "downtimes": "paradas",
        "setups": "setup",
        "quality": "qualidade",
        "standard-vs-actual": "tempo_padrao_x_real",
        "badge-allocation": "rateio_cracha",
        "chronoanalysis": "cronoanalise",
        "capacity": "capacidade",
        "reliability": "confiabilidade",
    }
    key = aliases.get(analysis_type.strip().casefold())
    if key is None:
        raise AppError("unknown_analysis", "Análise solicitada não existe.", status_code=404)
    # Só a tela de Paradas lê o consolidado + diferença; os demais consumidores
    # de ``analise("paradas")`` (IA, relatório, Telegram) seguem com a lista.
    payload = facade.paradas_tela(filters) if key == "paradas" else facade.analise(key, filters)
    if key == "oee":
        overview = facade.inicio(filters, include_insights=False)
        oee = payload
        return {
            "periodo": filters.to_dict(),
            "oee": oee,
            "value": oee.get("value"),
            "components": overview.get("kpis", {}),
            "availability": oee.get("availability", "dados_insuficientes"),
            "reason": oee.get("reason"),
            "evolution": oee.get("evolution"),
            "extended_metrics": oee.get("extended_metrics"),
            "losses_breakdown": oee.get("losses_breakdown"),
        }
    return payload
