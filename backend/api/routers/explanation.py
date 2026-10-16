"""Explicação clicável das métricas de tempo (``GET /management/explicacao``).

Rota fina: filtros iguais aos de ``/management/overview`` (mesma dependência
``analytics_filter``) e a conta inteira em ``MetricExplanationService``.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.core.permissions import can_access_management_web
from backend.api.dependencies.auth import require_management_user
from backend.api.dependencies.bulkhead import management_read_slot
from backend.api.dependencies.facade import get_frontend_facade
from backend.api.dependencies.filters import analytics_filter
from backend.api.errors import AppError
from backend.api.schemas.auth import SessionUser
from backend.api.schemas.explanation import ExplanationResponse
from mes.contracts import AnalyticsFilter
from mes.services.metric_explanation import MetricExplanationService, UnknownMetricError


router = APIRouter(
    prefix="/management",
    tags=["Gestão"],
    # Autorização antes do bulkhead: quem não pode ver não ocupa vaga de leitura.
    dependencies=[Depends(require_management_user), Depends(management_read_slot)],
)


def redact_operator_names(tree: dict, level: str) -> dict:
    """Remove o nome do operador dos trechos para quem não é de gestão.

    A rota já exige gestão; esta é a segunda trava, caso a lista de níveis da
    rota seja ampliada um dia.
    """

    if can_access_management_web(level):
        return tree

    def blank(nodes: list[dict]) -> None:
        for node in nodes:
            detail = node.get("detail")
            if detail is not None and "who" in detail:
                detail["who"] = None
            blank(node.get("children") or [])

    blank(tree.get("children") or [])
    return tree


@router.get("/explicacao", response_model=ExplanationResponse)
def explain_metric(
    metric: str = Query(min_length=1, max_length=64),
    filters: AnalyticsFilter = Depends(analytics_filter),
    user: SessionUser = Depends(require_management_user),
    facade=Depends(get_frontend_facade),
):
    service = MetricExplanationService(facade.management, facade.db)
    try:
        tree = service.explain(metric.strip(), filters)
    except UnknownMetricError as exc:
        raise AppError("unknown_metric", str(exc), status_code=422) from exc
    return redact_operator_names(tree.to_dict(), user.role)
