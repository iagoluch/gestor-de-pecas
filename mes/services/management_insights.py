"""Projeção gerencial explicável e orientada a exceções.

O serviço combina somente saídas já calculadas por serviços canônicos. Não
recalcula KPI no frontend, não cria metas implícitas e não usa um escore opaco
para ordenar recursos. Todo alerta carrega o fato e a referência que o sustenta.
"""

from __future__ import annotations

from datetime import datetime
from typing import Iterable, Optional

from mes.contracts import (
    AnalyticsFilter,
    InsightEvidence,
    KpiExplanation,
    ManagementException,
    MetricValue,
)
from mes.domain import DataAvailability


_KPI_LABELS = {
    "oee": "OEE",
    "availability": "Disponibilidade",
    "performance": "Performance",
    "ftt": "FTT / Qualidade",
}

_SEVERITY_PRIORITY = {
    "alta": 3,
    "atencao": 2,
    "informativa": 1,
}


class ManagementInsightsService:
    """Monta explicações e exceções determinísticas para um único filtro."""

    def __init__(
        self,
        db,
        *,
        management,
        analytics,
        now_func=None,
        simulation_mode=False,
    ):
        self.db = db
        self.management = management
        self.analytics = analytics
        self._now = now_func or datetime.now
        self.simulation_mode = bool(simulation_mode)
        self._cache = {}

    def build(self, filters: AnalyticsFilter, *, overview: Optional[dict] = None) -> dict:
        cache_key = ("insights", filters)
        if cache_key in self._cache:
            return self._cache[cache_key]

        overview = overview or self.management.get_overview(filters)
        downtimes = self.analytics.downtimes(filters)
        standard_actual = self.analytics.standard_vs_actual(filters)
        quality = self.analytics.quality(filters)
        targets = self._load_targets(filters)

        explanations = self._build_explanations(
            filters,
            overview=overview,
            downtimes=downtimes,
            standard_actual=standard_actual,
            quality=quality,
        )
        losses = self._build_losses(downtimes)
        critical_resources = self._build_critical_resources(downtimes)
        exceptions = self._build_exceptions(
            filters,
            overview=overview,
            downtimes=downtimes,
            standard_actual=standard_actual,
            targets=targets,
        )

        limitations = []
        if targets is None:
            limitations.append({
                "code": "kpi_targets_not_configured",
                "message": (
                    "Nenhuma fonte de metas gerenciais foi configurada; o sistema não cria "
                    "limites de OEE, Disponibilidade, Performance ou FTT por inferência."
                ),
            })
        unavailable = [
            _KPI_LABELS[key]
            for key, explanation in explanations.items()
            if explanation.metric.availability != DataAvailability.AVAILABLE
        ]
        if unavailable:
            limitations.append({
                "code": "kpis_unavailable_for_filter",
                "message": "Indicadores sem dados suficientes no filtro: " + ", ".join(unavailable) + ".",
            })

        payload = {
            "periodo": filters.to_dict(),
            "generated_at": self._now().isoformat(),
            "exceptions": [item.to_dict() for item in exceptions],
            "exception_count": len(exceptions),
            "losses": losses,
            "critical_resources": critical_resources,
            "kpi_explanations": {
                key: explanation.to_dict()
                for key, explanation in explanations.items()
            },
            "limitations": limitations,
            "policies": {
                "calculation": "backend_only",
                "priority": (
                    "Severidade por natureza do fato (parada atual não programada = alta; "
                    "perda no período, desvio acima do padrão ou meta configurada = atenção), "
                    "seguida do impacto físico absoluto."
                ),
                "resource_ranking": (
                    "Ordenação direta pelo tempo físico de parada no período; sem escore composto."
                ),
                "thresholds": "Somente metas explicitamente configuradas; nenhum limite arbitrário.",
            },
            "availability": (
                DataAvailability.AVAILABLE.value
                if exceptions or losses or critical_resources
                else DataAvailability.NO_RECORDS.value
            ),
            "simulation_only": self.simulation_mode,
        }
        self._cache[cache_key] = payload
        return payload

    def explain_kpi(
        self,
        key: str,
        filters: AnalyticsFilter,
        *,
        overview: Optional[dict] = None,
    ) -> dict:
        normalized = str(key or "").strip().casefold()
        if normalized not in _KPI_LABELS:
            raise ValueError("KPI gerencial não suportado.")
        return self.build(filters, overview=overview)["kpi_explanations"][normalized]

    def _build_explanations(self, filters, *, overview, downtimes, standard_actual, quality):
        period = filters.to_dict()
        kpis = overview.get("kpis") or {}
        downtime_items = list(downtimes.get("items") or [])
        downtime_evidence = tuple(_downtime_evidence(item) for item in downtime_items[:50])
        downtime_causes = tuple(
            {
                "cause": item.get("motivo"),
                "impact_value": _seconds(item),
                "impact_unit": "s",
            }
            for item in (downtimes.get("by_reason") or [])
        )
        downtime_resources = tuple(
            {
                "resource": item.get("recurso"),
                "impact_value": _seconds(item),
                "impact_unit": "s",
            }
            for item in (downtimes.get("by_resource") or [])
        )
        largest_downtime = downtime_causes[0] if downtime_causes else None

        hours = overview.get("hours") or {}
        availability_components = tuple(
            {
                "key": key,
                "label": label,
                "value": float(hours.get(field) or 0.0),
                "unit": "s",
                "source_field": field,
            }
            for key, label, field in (
                ("production", "Produção", "production_seconds"),
                ("setup", "Setup produtivo", "setup_seconds"),
                ("rework", "Retrabalho", "rework_seconds"),
                ("activity_without_op", "Atividade sem OP", "activity_without_op_seconds"),
                ("downtime", "Paradas", "downtime_seconds"),
                ("no_demand", "Recurso sem demanda", "no_demand_seconds"),
                ("out_of_shift", "Fora do turno", "out_of_shift_seconds"),
            )
        )

        comparable = [
            item for item in (standard_actual.get("items") or [])
            if item.get("tempo_padrao_estimado_segundos") is not None
            and item.get("tempo_producao_real_segundos") is not None
        ]
        positive_deviations = sorted(
            (item for item in comparable if float(item.get("desvio_segundos") or 0.0) > 0.0),
            key=lambda item: (
                float(item.get("desvio_segundos") or 0.0),
                str(item.get("op") or ""),
            ),
            reverse=True,
        )
        time_bases = overview.get("kpi_time_bases") or {}
        performance_components = tuple(
            {
                "key": key,
                "label": label,
                "value": float(time_bases[field]),
                "unit": "s",
                "source_field": field,
                "formula_role": formula_role,
            }
            for key, label, field, formula_role in (
                (
                    "productive_net",
                    "Tempo produtivo líquido canônico",
                    "productive_net_seconds",
                    "numerador",
                ),
                (
                    "worked",
                    "Tempo trabalhado canônico",
                    "worked_seconds",
                    "denominador",
                ),
                (
                    "performance_difference",
                    "Numerador menos denominador (positivo = Performance acima de 100%)",
                    "performance_difference_seconds",
                    "evidencia_relacao",
                ),
                (
                    "standard_run",
                    "Tempo padrão das peças boas",
                    "standard_run_seconds",
                    "componente_numerador",
                ),
                (
                    "supporting_productive",
                    "Tempo produtivo de apoio",
                    "supporting_productive_seconds",
                    "componente_numerador",
                ),
            )
            if time_bases.get(field) is not None
        )
        performance_causes = tuple(_performance_cause(item) for item in positive_deviations)
        performance_evidence = tuple(_performance_evidence(item) for item in comparable[:50])

        totals = quality.get("totals") or {}
        quality_components = tuple(
            {
                "key": key,
                "label": label,
                "value": int(totals.get(key) or 0),
                "unit": "peças",
            }
            for key, label in (
                ("boa", "Peças boas"),
                ("refugo", "Refugo"),
                ("retrabalho", "Retrabalho"),
            )
        )
        quality_causes = tuple(
            {
                "cause": item.get("motivo"),
                "kind": kind,
                "impact_value": int(item.get("quantidade") or 0),
                "impact_unit": "peças",
            }
            for kind, rows in (
                ("refugo", quality.get("scrap_reasons") or []),
                ("retrabalho", quality.get("rework_reasons") or []),
            )
            for item in rows
        )
        quality_causes = tuple(sorted(
            quality_causes,
            key=lambda item: (item["impact_value"], str(item.get("cause") or "")),
            reverse=True,
        ))
        quality_evidence = tuple(
            _quality_evidence(item)
            for item in (quality.get("evidence") or [])[:50]
        )

        component_metrics = [
            (key, _metric(kpis.get(key)))
            for key in ("availability", "performance", "ftt")
        ]
        available_components = [
            (key, metric)
            for key, metric in component_metrics
            if metric.value is not None and metric.availability == DataAvailability.AVAILABLE
        ]
        lowest_component = None
        if available_components:
            key, metric = min(available_components, key=lambda item: float(item[1].value))
            lowest_component = {
                "key": key,
                "label": _KPI_LABELS[key],
                "value": metric.value,
                "unit": metric.unit,
                "meaning": "Menor componente disponível observado no filtro atual; não é uma meta inferida.",
            }

        simulation_only = self.simulation_mode
        oee_components = tuple({
            "key": key,
            "label": _KPI_LABELS[key],
            **metric.to_dict(),
        } for key, metric in component_metrics)

        return {
            "oee": KpiExplanation(
                key="oee",
                label=_KPI_LABELS["oee"],
                metric=_metric(kpis.get("oee")),
                period=period,
                components=oee_components,
                largest_impact=lowest_component,
                causes=tuple(filter(None, (largest_downtime, performance_causes[0] if performance_causes else None, quality_causes[0] if quality_causes else None))),
                resources=downtime_resources,
                evidence=tuple((*downtime_evidence, *performance_evidence, *quality_evidence))[:50],
                simulation_only=simulation_only,
                limitation=_metric(kpis.get("oee")).reason,
            ),
            "availability": KpiExplanation(
                key="availability",
                label=_KPI_LABELS["availability"],
                metric=_metric(kpis.get("availability")),
                period=period,
                components=availability_components,
                largest_impact=largest_downtime,
                causes=downtime_causes,
                resources=downtime_resources,
                evidence=downtime_evidence,
                simulation_only=simulation_only,
                limitation=_metric(kpis.get("availability")).reason,
            ),
            "performance": KpiExplanation(
                key="performance",
                label=_KPI_LABELS["performance"],
                metric=_metric(kpis.get("performance")),
                period=period,
                components=performance_components,
                largest_impact=performance_causes[0] if performance_causes else None,
                causes=performance_causes,
                resources=_rank_performance_resources(positive_deviations),
                evidence=performance_evidence,
                simulation_only=simulation_only,
                limitation=(
                    _metric(kpis.get("performance")).reason
                    if comparable
                    else "Não há operações com tempo padrão e tempo real comparáveis no filtro atual."
                ),
            ),
            "ftt": KpiExplanation(
                key="ftt",
                label=_KPI_LABELS["ftt"],
                metric=_metric(kpis.get("ftt")),
                period=period,
                components=quality_components,
                largest_impact=quality_causes[0] if quality_causes else None,
                causes=quality_causes,
                resources=_rank_quality_resources(quality.get("evidence") or []),
                evidence=quality_evidence,
                simulation_only=simulation_only,
                limitation=_metric(kpis.get("ftt")).reason,
            ),
        }

    def _build_losses(self, downtimes):
        evidence_by_reason = {}
        for item in downtimes.get("items") or []:
            reason = str(item.get("motivo") or "Não informado")
            evidence_by_reason.setdefault(reason.casefold(), []).append(_downtime_evidence(item))
        return [
            {
                "rank": index,
                "type": "physical_downtime",
                "cause": item.get("motivo"),
                "impact_value": _seconds(item),
                "impact_unit": "s",
                "evidence": [entry.to_dict() for entry in evidence_by_reason.get(str(item.get("motivo") or "").casefold(), [])[:20]],
            }
            for index, item in enumerate(downtimes.get("by_reason") or [], start=1)
            if _seconds(item) > 0.0
        ]

    def _build_critical_resources(self, downtimes):
        evidence_by_resource = {}
        for item in downtimes.get("items") or []:
            resource = str(item.get("recurso") or "Não informado")
            evidence_by_resource.setdefault(resource.casefold(), []).append(_downtime_evidence(item))
        return [
            {
                "rank": index,
                "resource": item.get("recurso"),
                "impact_value": _seconds(item),
                "impact_unit": "s",
                "criterion": "tempo_fisico_de_parada_no_periodo",
                "evidence": [entry.to_dict() for entry in evidence_by_resource.get(str(item.get("recurso") or "").casefold(), [])[:20]],
            }
            for index, item in enumerate(downtimes.get("by_resource") or [], start=1)
            if _seconds(item) > 0.0
        ]

    def _build_exceptions(self, filters, *, overview, downtimes, standard_actual, targets):
        period = filters.to_dict()
        exceptions = []
        now = self._now()
        current_context = filters.inicio <= now <= filters.fim

        for item in downtimes.get("items") or []:
            if (
                not current_context
                or not item.get("em_andamento")
                or item.get("programada") is not False
            ):
                continue
            resource = str(item.get("recurso") or "Não informado")
            seconds = float(item.get("segundos") or 0.0)
            exceptions.append(ManagementException(
                id=f"current-unplanned-stop:{item.get('estado_recurso_id') or item.get('evento_id') or resource}",
                type="current_unplanned_downtime",
                severity="alta",
                priority=_SEVERITY_PRIORITY["alta"],
                entity_type="resource",
                entity_id=resource,
                title=f"{resource} está em parada não programada",
                summary=f"Parada em andamento: {item.get('motivo') or 'motivo não informado'}.",
                justification="O estado físico atual do recurso registra uma parada não programada em andamento.",
                period=period,
                sector=item.get("setor"),
                resource=resource,
                op=item.get("op"),
                operation=_text(item.get("operacao")),
                current_value=seconds,
                unit="s",
                cause=item.get("motivo"),
                impact_value=seconds,
                impact_unit="s",
                evidence=(_downtime_evidence(item),),
            ))

        evidence_by_resource = {}
        for item in downtimes.get("items") or []:
            resource = str(item.get("recurso") or "Não informado")
            evidence_by_resource.setdefault(resource.casefold(), []).append(_downtime_evidence(item))
        for item in downtimes.get("by_resource") or []:
            seconds = _seconds(item)
            if seconds <= 0.0:
                continue
            resource = str(item.get("recurso") or "Não informado")
            exceptions.append(ManagementException(
                id=f"downtime-period:{resource.casefold()}",
                type="physical_downtime_in_period",
                severity="atencao",
                priority=_SEVERITY_PRIORITY["atencao"],
                entity_type="resource",
                entity_id=resource,
                title=f"{resource} concentrou tempo de parada",
                summary="Impacto físico acumulado no período selecionado.",
                justification="O tempo é consolidado por recurso, removendo sobreposição de OPs simultâneas.",
                period=period,
                resource=resource,
                current_value=seconds,
                unit="s",
                impact_value=seconds,
                impact_unit="s",
                evidence=tuple(evidence_by_resource.get(resource.casefold(), [])[:20]),
            ))

        for item in standard_actual.get("items") or []:
            deviation = item.get("desvio_segundos")
            if deviation is None or float(deviation) <= 0.0:
                continue
            op = str(item.get("op") or "Não informada")
            operation = _text(item.get("operacao")) or "Não informada"
            exceptions.append(ManagementException(
                id=f"standard-deviation:{item.get('apontamento_id') or op + ':' + operation}",
                type="actual_time_above_standard",
                severity="atencao",
                priority=_SEVERITY_PRIORITY["atencao"],
                entity_type="operation",
                entity_id=f"{op}:{operation}",
                title=f"OP {op} / operação {operation} acima do tempo padrão",
                summary="O tempo real comparável superou o tempo padrão já existente.",
                justification="Comparação direta entre tempo real canônico e tempo padrão cadastrado; sem tolerância inferida.",
                period=period,
                sector=item.get("setor"),
                resource=item.get("recurso_real"),
                op=item.get("op"),
                operation=_text(item.get("operacao")),
                current_value=float(item.get("tempo_producao_real_segundos") or 0.0),
                reference_value=float(item.get("tempo_padrao_estimado_segundos") or 0.0),
                deviation=float(deviation),
                unit="s",
                impact_value=float(deviation),
                impact_unit="s",
                evidence=(_performance_evidence(item),),
            ))

        if targets is not None:
            for target in targets:
                key = str(target.get("kpi") or target.get("indicador") or "").strip().casefold()
                if key not in _KPI_LABELS:
                    continue
                reference = _number(target.get("target", target.get("meta")))
                metric = _metric((overview.get("kpis") or {}).get(key))
                if reference is None or metric.value is None or metric.availability != DataAvailability.AVAILABLE:
                    continue
                current = float(metric.value)
                if current >= reference:
                    continue
                deviation = current - reference
                scope = str(target.get("id") or target.get("codigo") or "geral")
                exceptions.append(ManagementException(
                    id=f"configured-target:{key}:{scope}",
                    type="configured_kpi_target",
                    severity="atencao",
                    priority=_SEVERITY_PRIORITY["atencao"],
                    entity_type="kpi",
                    entity_id=key,
                    title=f"{_KPI_LABELS[key]} abaixo da meta configurada",
                    summary=f"Valor atual {current:.2f}% e meta {reference:.2f}%.",
                    justification="Comparação com meta explicitamente fornecida pelo repositório no mesmo contexto de filtro.",
                    period=period,
                    sector=target.get("setor"),
                    resource=target.get("recurso"),
                    current_value=current,
                    reference_value=reference,
                    deviation=deviation,
                    unit=metric.unit or "%",
                    impact_value=abs(deviation),
                    impact_unit="p.p.",
                    evidence=(InsightEvidence(
                        source=str(target.get("source") or "metas_indicadores"),
                        source_id=_text(target.get("id") or target.get("codigo")),
                        kind="configured_target",
                        sector=target.get("setor"),
                        resource=target.get("recurso"),
                        details={"kpi": key, "target": reference},
                    ),),
                ))

        exceptions.sort(key=lambda item: (
            -item.priority,
            -(item.impact_value or 0.0),
            item.title.casefold(),
        ))
        return exceptions[:12]

    def _load_targets(self, filters):
        loader = getattr(self.db, "listar_metas_indicadores", None)
        if not callable(loader):
            return None
        return list(loader(
            inicio=filters.inicio,
            fim=filters.fim,
            setor=filters.setor,
            recurso=filters.recurso,
            turno=filters.turno,
        ) or [])


def _metric(raw) -> MetricValue:
    raw = raw or {}
    availability_value = raw.get("availability") or DataAvailability.INSUFFICIENT_DATA.value
    try:
        availability = DataAvailability(str(availability_value))
    except ValueError:
        availability = DataAvailability.INSUFFICIENT_DATA
    return MetricValue(
        value=_number(raw.get("value")),
        availability=availability,
        unit=raw.get("unit"),
        reason=raw.get("reason"),
    )


def _downtime_evidence(item) -> InsightEvidence:
    return InsightEvidence(
        source=str(item.get("fonte") or "eventos_estado_recurso"),
        kind="parada",
        source_id=_text(item.get("estado_recurso_id") or item.get("evento_id") or item.get("apontamento_id")),
        sector=item.get("setor"),
        resource=item.get("recurso"),
        op=item.get("op"),
        operation=_text(item.get("operacao")),
        product=item.get("produto"),
        reason=item.get("motivo"),
        start=item.get("inicio"),
        end=item.get("fim"),
        duration_seconds=float(item.get("segundos") or 0.0),
        details={
            "planned": item.get("programada"),
            "automatic": item.get("automatica"),
            "ongoing": bool(item.get("em_andamento")),
        },
    )


def _performance_evidence(item) -> InsightEvidence:
    return InsightEvidence(
        source=str(item.get("fonte_tempo_producao") or "tempo_real_operacao"),
        kind="tempo_padrao_x_real",
        source_id=_text(item.get("apontamento_id")),
        sector=item.get("setor"),
        resource=item.get("recurso_real"),
        op=item.get("op"),
        operation=_text(item.get("operacao")),
        product=item.get("produto"),
        duration_seconds=_number(item.get("tempo_producao_real_segundos")),
        details={
            "standard_seconds": item.get("tempo_padrao_estimado_segundos"),
            "actual_seconds": item.get("tempo_producao_real_segundos"),
            "deviation_seconds": item.get("desvio_segundos"),
            "deviation_percentage": item.get("desvio_percentual"),
            "good_quantity": item.get("quantidade_boa"),
        },
    )


def _quality_evidence(item) -> InsightEvidence:
    return InsightEvidence(
        source=str(item.get("source") or "eventos_quantidade_producao"),
        kind=str(item.get("type") or "quantidade"),
        source_id=_text(item.get("event_id")),
        sector=item.get("sector"),
        resource=item.get("resource"),
        op=item.get("op"),
        operation=_text(item.get("operation")),
        product=item.get("product"),
        reason=item.get("reason"),
        occurred_at=item.get("occurred_at"),
        quantity=int(item.get("quantity") or 0),
    )


def _performance_cause(item):
    return {
        "cause": "Tempo real acima do padrão na operação (desvio local desfavorável)",
        "op": item.get("op"),
        "operation": item.get("operacao"),
        "resource": item.get("recurso_real"),
        "current_value": item.get("tempo_producao_real_segundos"),
        "reference_value": item.get("tempo_padrao_estimado_segundos"),
        "impact_value": float(item.get("desvio_segundos") or 0.0),
        "impact_unit": "s",
        "meaning": (
            "Evidência local de perda; não substitui a base agregada usada no cálculo da Performance."
        ),
    }


def _rank_performance_resources(items: Iterable[dict]):
    totals = {}
    for item in items:
        resource = str(item.get("recurso_real") or "Não informado")
        totals[resource] = totals.get(resource, 0.0) + float(item.get("desvio_segundos") or 0.0)
    return tuple(
        {"resource": resource, "impact_value": seconds, "impact_unit": "s"}
        for resource, seconds in sorted(totals.items(), key=lambda pair: (pair[1], pair[0].casefold()), reverse=True)
    )


def _rank_quality_resources(evidence: Iterable[dict]):
    totals = {}
    for item in evidence:
        if item.get("type") not in {"refugo", "retrabalho"}:
            continue
        resource = str(item.get("resource") or "Não informado")
        totals[resource] = totals.get(resource, 0) + int(item.get("quantity") or 0)
    return tuple(
        {"resource": resource, "impact_value": quantity, "impact_unit": "peças"}
        for resource, quantity in sorted(totals.items(), key=lambda pair: (pair[1], pair[0].casefold()), reverse=True)
    )


def _number(value):
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _seconds(item):
    return float(item.get("segundos", item.get("seconds")) or 0.0)


def _text(value):
    if value is None:
        return None
    return str(value)
