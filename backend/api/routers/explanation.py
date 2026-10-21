"""Explicação clicável das métricas (``GET /management/explicacao``): tempo e valor.

Rota fina: filtros iguais aos de ``/management/overview`` (mesma dependência
``analytics_filter``) e a conta inteira em ``MetricExplanationService`` (tempo) ou ``ValueExplanationService`` (valor).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.core.permissions import can_access_management_web, can_manage_standard_time
from backend.api.dependencies.auth import require_management_user
from backend.api.dependencies.bulkhead import management_read_slot
from backend.api.dependencies.facade import get_frontend_facade
from backend.api.dependencies.filters import analytics_filter
from backend.api.errors import AppError
from backend.api.schemas.auth import SessionUser
from backend.api.schemas.explanation import ExplanationResponse, ValueExplanationResponse
from mes.contracts import AnalyticsFilter
from mes.services.cut_explanation import CutExplanationService
from mes.services.kpi_explanation import KpiExplanationService
from mes.services.metric_explanation import MetricExplanationService, UnknownMetricError
from mes.services.quality_explanation import QualityExplanationService
from mes.services.standard_time_explanation import StandardTimeExplanationService
from mes.services.value_explanation import ValueExplanationService


# Despacho por prefixo do id: ``tempo.*`` fica no serviço de tempo (que também
# responde 422 para id desconhecido); cada família nova entra aqui, com a fonte
# que a própria tela usa.
_VALUE_SERVICES = {
    # Visão Geral (``ManagementService.get_overview``).
    "qtd.": lambda facade: ValueExplanationService(facade.management, facade.db),
    # Análises > Qualidade (``facade.analytics.quality``) e Alertas/Auditoria
    # (``facade.audit_service.run_period``, o mesmo de ``facade.auditoria``).
    "qld.": lambda facade: QualityExplanationService(facade.analytics, facade.audit_service),
    # OEE e componentes: Visão Geral e Análises > OEE (o mesmo ``get_overview``).
    "kpi.": lambda facade: KpiExplanationService(facade.management),
    # Rastreabilidade > Lote / Material / Nesting (``management.get_nesting_times``).
    "cut.": lambda facade: CutExplanationService(facade.management),
    # Produção > Tempo padrão (``db.listar_tempos_padrao`` e o último recálculo) e
    # Análises > Padrão x real (``facade.analytics.standard_vs_actual``).
    "std.": lambda facade: StandardTimeExplanationService(facade.db, facade.analytics),
}
_VALUE_PREFIXES = tuple(_VALUE_SERVICES)

# S1–S5 explicam a tela de Tempo padrão, que só a manufatura e o admin abrem;
# S6 (Padrão x real) é lido pela gestão, como a página de Análises.
_STANDARD_TIME_LINE_METRICS = frozenset({
    "std.protheus", "std.manual", "std.estimado", "std.fonte", "std.recalculo",
})


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
            if detail is not None:
                for key in ("who", "operador"):
                    if key in detail:
                        detail[key] = None
            blank(node.get("children") or [])

    blank(tree.get("children") or [])
    return tree


def explain_for_user(facade, metric: str, filters: AnalyticsFilter, user: SessionUser) -> dict:
    """Recalcula a árvore no servidor (422 para métrica desconhecida) e oculta o operador se preciso.

    Compartilhado com o chat da IA (``/ai/.../messages`` com ``explanation``):
    uma única fonte da árvore, nunca aceita do cliente.
    """
    metric = metric.strip()
    if metric in _STANDARD_TIME_LINE_METRICS and not can_manage_standard_time(user.role):
        raise AppError(
            "standard_time_access_denied",
            "Só a engenharia de manufatura e a conta administradora acessam o tempo padrão.",
            status_code=403,
        )
    factory = next(
        (build for prefix, build in _VALUE_SERVICES.items() if metric.startswith(prefix)),
        None,
    )
    service = (
        factory(facade)
        if factory is not None
        else MetricExplanationService(facade.management, facade.db)
    )
    try:
        tree = service.explain(metric, filters)
    except UnknownMetricError as exc:
        raise AppError("unknown_metric", str(exc), status_code=422) from exc
    return redact_operator_names(tree.to_dict(), user.role)


@router.get("/explicacao", response_model=ExplanationResponse | ValueExplanationResponse)
def explain_metric(
    metric: str = Query(min_length=1, max_length=64),
    filters: AnalyticsFilter = Depends(analytics_filter),
    user: SessionUser = Depends(require_management_user),
    facade=Depends(get_frontend_facade),
):
    return explain_for_user(facade, metric, filters, user)
