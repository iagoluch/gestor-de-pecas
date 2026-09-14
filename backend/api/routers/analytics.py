from fastapi import APIRouter, Depends

from backend.api.dependencies.auth import require_management_user
from backend.api.dependencies.facade import get_frontend_facade
from backend.api.dependencies.filters import analytics_filter
from backend.api.errors import AppError
from backend.api.schemas.auth import SessionUser
from mes.contracts import AnalyticsFilter


router = APIRouter(prefix="/analytics", tags=["Análises"])


@router.get("")
def all_analytics(
    filters: AnalyticsFilter = Depends(analytics_filter),
    _user: SessionUser = Depends(require_management_user),
    facade=Depends(get_frontend_facade),
):
    return facade.analises(filters)


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
        "chronoanalysis": "cronoanalise",
        "capacity": "capacidade",
        "reliability": "confiabilidade",
    }
    key = aliases.get(analysis_type.strip().casefold())
    if key is None:
        raise AppError("unknown_analysis", "Análise solicitada não existe.", status_code=404)
    payload = facade.analise(key, filters)
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
        }
    return payload
