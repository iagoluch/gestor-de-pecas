"""Serviços gerenciais independentes da camada de apresentação.

A camada expõe dados estruturados e marca explicitamente quando uma métrica
não pode ser calculada. Isso evita que o frontend Web interprete
"ausência de dado" como zero.
"""

import math
from collections import defaultdict
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timedelta
from typing import Optional

from app.core.operator_sectors import OPERATOR_SECTORS
from app.core.resource_mapping import resolve_resource_identity, resource_canonical_sector, resource_display_name
from mes.analytics.physical_time import (
    PhysicalInputSegment,
    consolidate_physical_time,
    restrict_to_resources,
)
from mes.analytics.oee import OEE_CONTRACT, calculate_oee, oee_seconds_by_category
from mes.analytics.resource_state import build_physical_state_inputs
from mes.analytics.timeline import build_operator_timeline
from mes.contracts import AnalyticsFilter, MetricValue
from mes.domain import (
    DataAvailability,
    EventCategory,
    ManufacturingRules,
    StopClassification,
)
from mes.domain.standard_time import (
    estimated_view_standard_seconds,
    official_standard_seconds,
)
from mes.services.calendar import CalendarService


class ManagementService:
    _MAX_OEE_EVOLUTION_POINTS = 31
    _TREND_RECENT_EVENTS_LIMIT = 8
    # Mesmo piso da validação de período da API: antes disso não há histórico.
    _MIN_PERIOD_YEAR = 2000
    _TREND_KPI_KEYS = ("oee", "availability", "performance", "ftt")
    _TREND_HOURS_KEYS = (
        "production_seconds",
        "setup_seconds",
        "downtime_seconds",
        "rework_seconds",
        "activity_without_op_seconds",
        "no_demand_seconds",
        "out_of_shift_seconds",
    )

    def __init__(self, db, now_func=None, simulation_mode=False):
        self.db = db
        self._now = now_func or datetime.now
        self.simulation_mode = bool(simulation_mode)
        self._overview_cache = {}

    def get_overview(self, filters: AnalyticsFilter) -> dict:
        if filters in self._overview_cache:
            return self._overview_cache[filters]
        facts = self._load_operational_facts(filters)
        quantity_source_available, quantity_events = self._load_quantity_events(filters)
        quantity_evidence = bool(quantity_events) if quantity_source_available else bool(facts)
        quantity_source = (
            "eventos_quantidade_producao"
            if quantity_source_available
            else "apontamentos_operacionais_fallback"
        )
        totals = defaultdict(float)
        good = scrap = rework_qty = 0
        # Parte das quantidades que é peça recuperada do retrabalho: segue na
        # produção física, mas fica fora do FTT (regra da manufatura, 19/10/2026).
        recovered_good = recovered_scrap = recovered_rework = 0
        standard_run_seconds = 0.0
        good_without_standard = 0
        # Leitura "estimada": mesma fórmula, padrão oficial + estimado do Gestor.
        estimated_run_seconds = 0.0
        estimated_good_without_standard = 0
        good_with_estimated_standard = 0
        resources = set()
        ops = set()
        # Mesmas entradas do calculador canônico, agregadas por setor, para que
        # o OEE do setor saia de ``calculate_oee`` e não de uma fórmula paralela.
        sectors = defaultdict(lambda: {
            "good": 0,
            "scrap": 0,
            "rework": 0,
            "recovered": {"boa": 0, "refugo": 0, "retrabalho": 0},
            "seconds": defaultdict(float),
            "ops": set(),
            "standard_run_seconds": 0.0,
            "good_without_standard": 0,
            "planned_downtime_seconds": 0.0,
            "nesting_standard_seconds": 0.0,
        })
        resource_inputs = defaultdict(lambda: {
            "resource": None,
            "sector": None,
            "good": 0,
            "scrap": 0,
            "rework": 0,
            "recovered": {"boa": 0, "refugo": 0, "retrabalho": 0},
            "standard_run_seconds": 0.0,
            "good_without_standard": 0,
            "estimated_run_seconds": 0.0,
            "estimated_good_without_standard": 0,
            "good_with_estimated_standard": 0,
            "seconds": defaultdict(float),
            "planned_downtime_seconds": 0.0,
            "nesting_standard_seconds": 0.0,
        })

        def resource_bucket(resource, sector=None):
            name = str(resource or "").strip()
            if not name:
                return None
            bucket = resource_inputs[name.casefold()]
            if bucket["resource"] is None:
                bucket["resource"] = name
            if bucket["sector"] is None and str(sector or "").strip():
                bucket["sector"] = str(sector).strip()
            return bucket

        for row in facts:
            if self._fact_window(row, filters) is None:
                continue
            resource = str(row.get("maquina") or "").strip()
            op = str(row.get("op") or "").strip()
            sector = str(row.get("tipo_setor") or "").strip() or "Não informado"
            if not quantity_source_available:
                good += int(row.get("quantidade_boa") or 0)
                scrap += int(row.get("quantidade_refugo") or 0)
                rework_qty += int(row.get("quantidade_retrabalho") or 0)
                if row.get("retorno_retrabalho_qualidade"):
                    # Apontamento de retorno do retrabalho: tudo o que ele
                    # lança é peça que já entrou na base do FTT.
                    recovered_good += int(row.get("quantidade_boa") or 0)
                    recovered_scrap += int(row.get("quantidade_refugo") or 0)
                    recovered_rework += int(row.get("quantidade_retrabalho") or 0)
                    sectors[sector]["recovered"]["boa"] += int(row.get("quantidade_boa") or 0)
                    sectors[sector]["recovered"]["refugo"] += int(row.get("quantidade_refugo") or 0)
                    sectors[sector]["recovered"]["retrabalho"] += int(row.get("quantidade_retrabalho") or 0)
                    if resource:
                        recovered_bucket = resource_bucket(resource, sector)["recovered"]
                        recovered_bucket["boa"] += int(row.get("quantidade_boa") or 0)
                        recovered_bucket["refugo"] += int(row.get("quantidade_refugo") or 0)
                        recovered_bucket["retrabalho"] += int(row.get("quantidade_retrabalho") or 0)
                if resource:
                    resource_input = resource_bucket(resource, sector)
                    resource_input["good"] += int(row.get("quantidade_boa") or 0)
                    resource_input["scrap"] += int(row.get("quantidade_refugo") or 0)
                    resource_input["rework"] += int(row.get("quantidade_retrabalho") or 0)
            if resource:
                resources.add(resource)
                resource_bucket(resource, sector)
            if op:
                ops.add(op)
            bucket = sectors[sector]
            # Performance oficial: Protheus + manual. A estimada soma o
            # estimado do Gestor sem tocar a oficial (decisão B, 06/10/2026).
            standard_unit_seconds = official_standard_seconds(row)
            view_unit_seconds = estimated_view_standard_seconds(row)
            row_good = max(0, int(row.get("quantidade_boa") or 0))
            if quantity_source_available:
                # S_boas e "sem padrão" contam só as peças boas lançadas DENTRO
                # do período, a mesma base de ``good``; o total do apontamento
                # inflaria cada dia que ele toca.
                period_good = _good_quantity_in_period(row, filters.inicio, filters.fim)
                if period_good is not None:
                    row_good = period_good
            row_bucket = resource_bucket(resource, sector) if resource else None
            if standard_unit_seconds is None:
                good_without_standard += row_good
                bucket["good_without_standard"] += row_good
                if row_bucket is not None:
                    row_bucket["good_without_standard"] += row_good
            else:
                row_standard_run_seconds = max(0.0, float(standard_unit_seconds)) * row_good
                standard_run_seconds += row_standard_run_seconds
                bucket["standard_run_seconds"] += row_standard_run_seconds
                if row_bucket is not None:
                    row_bucket["standard_run_seconds"] += row_standard_run_seconds
            if view_unit_seconds is None:
                estimated_good_without_standard += row_good
                if row_bucket is not None:
                    row_bucket["estimated_good_without_standard"] += row_good
            else:
                view_run_seconds = max(0.0, float(view_unit_seconds)) * row_good
                estimated_run_seconds += view_run_seconds
                if row_bucket is not None:
                    row_bucket["estimated_run_seconds"] += view_run_seconds
                if standard_unit_seconds is None:
                    good_with_estimated_standard += row_good
                    if row_bucket is not None:
                        row_bucket["good_with_estimated_standard"] += row_good
            if not quantity_source_available:
                bucket["good"] += int(row.get("quantidade_boa") or 0)
                bucket["scrap"] += int(row.get("quantidade_refugo") or 0)
                bucket["rework"] += int(row.get("quantidade_retrabalho") or 0)
            if op:
                bucket["ops"].add(op)

        state_source_available, state_rows = self._load_resource_states(filters)
        use_canonical_resource_state = bool(state_source_available and state_rows)
        if use_canonical_resource_state:
            resources.update(
                str(row.get("recurso") or "").strip()
                for row in state_rows
                if str(row.get("recurso") or "").strip()
            )

        if quantity_source_available:
            for event in quantity_events:
                qty = int(event.get("quantidade") or 0)
                kind = str(event.get("tipo") or "").strip().lower()
                sector = str(event.get("tipo_setor") or "").strip() or "Não informado"
                bucket = sectors[sector]
                resource_input = resource_bucket(event.get("recurso"), sector)
                recovered = (
                    max(0, min(qty, int(event.get("quantidade_recuperada") or 0)))
                    if kind in bucket["recovered"]
                    else 0
                )
                if recovered:
                    bucket["recovered"][kind] += recovered
                    if resource_input is not None:
                        resource_input["recovered"][kind] += recovered
                    if kind == "boa":
                        recovered_good += recovered
                    elif kind == "refugo":
                        recovered_scrap += recovered
                    else:
                        recovered_rework += recovered
                if kind == "boa":
                    good += qty
                    bucket["good"] += qty
                    if resource_input is not None:
                        resource_input["good"] += qty
                elif kind == "refugo":
                    scrap += qty
                    bucket["scrap"] += qty
                    if resource_input is not None:
                        resource_input["scrap"] += qty
                elif kind == "retrabalho":
                    rework_qty += qty
                    bucket["rework"] += qty
                    if resource_input is not None:
                        resource_input["rework"] += qty

        calendar_available = bool(self._has_calendar_configuration(filters))
        # Corte possui execução temporal por nesting em fonte própria. Quando o
        # filtro puder ser aplicado com segurança, o tempo físico de corte entra
        # na composição fabril sem ser confundido com uma OP agrupada.
        nesting_rows = self.get_nesting_times(filters)
        completed_nestings = [
            row for row in nesting_rows
            if str(row.get("status") or "").strip().casefold() == "finalizado"
        ]
        cutting_real_seconds = sum(
            float(row.get("real_periodo_segundos", row.get("real_segundos")) or 0)
            for row in nesting_rows
        )
        cutting_planned_seconds = sum(float(row.get("previsto_segundos") or 0) for row in nesting_rows)
        resources.update(
            str(row.get("maquina") or "").strip()
            for row in nesting_rows
            if str(row.get("maquina") or "").strip()
        )

        # Quantidade produzida pelo Corte. O setor executa fora de
        # `apontamentos_operacionais`, então a projeção canônica de Corte é a
        # única forma de o rollup gerencial enxergar boa/OPs do setor.
        cutting_production = self.get_cutting_production(filters)
        # Performance do Corte (opção A, manufatura 19/10/2026): o previsto do
        # nesting é o tempo padrão do Corte. É padrão oficial de origem
        # própria, nunca tempo manual ou estimado do Gestor.
        cutting_standard = self._cutting_standard(nesting_rows, filters)
        for sheet in cutting_standard["sheets"]:
            seconds = sheet["standard_seconds"]
            standard_run_seconds += seconds
            estimated_run_seconds += seconds
            sectors["Corte"]["standard_run_seconds"] += seconds
            sectors["Corte"]["nesting_standard_seconds"] += seconds
            sheet_bucket = resource_bucket(sheet["maquina"], "Corte")
            if sheet_bucket is not None:
                sheet_bucket["standard_run_seconds"] += seconds
                sheet_bucket["estimated_run_seconds"] += seconds
                sheet_bucket["nesting_standard_seconds"] += seconds
        for row in cutting_production:
            qty = max(0, int(row.get("quantidade") or 0))
            op = str(row.get("codigo_op") or "").strip()
            if not qty or not op:
                continue
            good += qty
            ops.add(op)
            bucket = sectors["Corte"]
            bucket["good"] += qty
            bucket["ops"].add(op)
            resource_input = resource_bucket(row.get("maquina"), "Corte")
            if resource_input is not None:
                resource_input["good"] += qty
            task = str(row.get("codigo_tarefa") or "").strip().casefold()
            if task in cutting_standard["tasks_with_standard"]:
                continue
            # Tarefa com chapa sem previsto (ou sem chapa visível): continua
            # sem padrão; nenhum número é inventado.
            good_without_standard += qty
            estimated_good_without_standard += qty
            bucket["good_without_standard"] += qty
            if resource_input is not None:
                resource_input["good_without_standard"] += qty
                resource_input["estimated_good_without_standard"] += qty
        if cutting_production:
            quantity_evidence = True

        nesting_physical_inputs, nesting_without_interval = self._nesting_physical_inputs(
            nesting_rows, filters
        )
        cutting_without_interval_seconds = 0.0
        cutting_without_interval_by_resource = defaultdict(float)
        cutting_without_interval_names: dict[str, str] = {}
        if not use_canonical_resource_state:
            for row in nesting_without_interval:
                # Compatibilidade com fontes antigas que conhecem a duração, mas
                # não fornecem início/fim. Sem intervalo não é possível detectar
                # sobreposição.
                legacy_seconds = float(
                    row.get("real_periodo_segundos", row.get("real_segundos")) or 0
                )
                cutting_without_interval_seconds += legacy_seconds
                machine = str(row.get("maquina") or "").strip()
                if machine:
                    cutting_without_interval_by_resource[machine.casefold()] += legacy_seconds
                    cutting_without_interval_names[machine.casefold()] = machine
                    resource_bucket(machine, "Corte")

        consolidation = self._consolidate_physical(
            filters,
            facts=facts,
            state_source_available=state_source_available,
            state_rows=state_rows,
            nesting_physical_inputs=nesting_physical_inputs,
        )
        physical = consolidation["consolidated"]
        physical_inputs = consolidation["inputs"]
        for category, seconds in physical["totals"].items():
            totals[category] += seconds
        if cutting_without_interval_seconds:
            totals[EventCategory.PRODUCTION] += cutting_without_interval_seconds

        downtime_by_classification = physical["totals_by_stop_classification"].get(
            EventCategory.DOWNTIME, {}
        )
        planned_downtime_seconds = float(
            downtime_by_classification.get(StopClassification.PLANNED, 0.0)
        )
        # Conta única do cartão: parada total menos a planejada. Inclui a parada
        # ainda sem classificação, que a Gestão precisa ver como não planejada.
        unplanned_downtime_seconds = max(
            0.0, float(totals[EventCategory.DOWNTIME]) - planned_downtime_seconds
        )
        resource_planned_downtime = {
            resource: float(
                categories.get(EventCategory.DOWNTIME, {}).get(
                    StopClassification.PLANNED, 0.0
                )
            )
            for resource, categories in physical["by_resource_stop_classification"].items()
        }

        # Recurso que só tem estado (sem apontamento nem quantidade) também
        # pertence a um setor: vem dos segmentos físicos que o formaram.
        sector_of_resource = {}
        for segment in physical_inputs:
            sector_of_resource.setdefault(segment.resource, segment.sector)
        for resource, category_totals in physical["by_resource"].items():
            bucket = resource_bucket(resource, sector_of_resource.get(resource))
            if bucket is None:
                continue
            for category, seconds in category_totals.items():
                bucket["seconds"][category] += seconds
            bucket["planned_downtime_seconds"] += resource_planned_downtime.get(
                resource, 0.0
            )
        for resource_key, seconds in cutting_without_interval_by_resource.items():
            resource_inputs[resource_key]["seconds"][EventCategory.PRODUCTION] += seconds

        for sector, category_totals in physical["by_sector"].items():
            bucket = sectors[sector]
            for category, seconds in category_totals.items():
                bucket["seconds"][category] += seconds
        for sector, categories in physical["by_sector_stop_classification"].items():
            sectors[sector]["planned_downtime_seconds"] += float(
                categories.get(EventCategory.DOWNTIME, {}).get(StopClassification.PLANNED, 0.0)
            )
        if cutting_without_interval_seconds:
            sectors["Corte"]["seconds"][EventCategory.PRODUCTION] += cutting_without_interval_seconds

        nesting_physical = consolidate_physical_time(nesting_physical_inputs)
        cutting_physical_seconds = (
            nesting_physical["physical_seconds"] + cutting_without_interval_seconds
        )
        productive_seconds = sum(
            totals[category]
            for category in EventCategory
            if ManufacturingRules.is_productive(category)
        )
        downtime_seconds = totals[EventCategory.DOWNTIME]
        measured_seconds = physical["physical_seconds"] + cutting_without_interval_seconds

        # Parada planejada sai da base temporal antes do cálculo. A fórmula
        # canônica permanece intacta; o que muda é o intervalo que entra nela.
        oee_calculation = calculate_oee(
            seconds_by_category=oee_seconds_by_category(
                totals, planned_downtime_seconds=planned_downtime_seconds
            ),
            good_quantity=good,
            scrap_quantity=scrap,
            rework_quantity=rework_qty,
            standard_run_seconds=standard_run_seconds,
            good_without_standard_quantity=good_without_standard,
            recovered_good_quantity=recovered_good,
            recovered_scrap_quantity=recovered_scrap,
            recovered_rework_quantity=recovered_rework,
        )
        availability = oee_calculation.availability
        performance = oee_calculation.performance
        estimated_performance = (
            calculate_oee(
                seconds_by_category=oee_seconds_by_category(
                    totals, planned_downtime_seconds=planned_downtime_seconds
                ),
                good_quantity=good,
                scrap_quantity=scrap,
                rework_quantity=rework_qty,
                standard_run_seconds=estimated_run_seconds,
                good_without_standard_quantity=estimated_good_without_standard,
                recovered_good_quantity=recovered_good,
                recovered_scrap_quantity=recovered_scrap,
                recovered_rework_quantity=recovered_rework,
            ).performance
            if good_with_estimated_standard
            else performance
        )
        ftt = oee_calculation.ftt
        oee = oee_calculation.oee
        time_bases = dict(oee_calculation.time_bases)

        # Indicadores extras (AE / Produtividade / Utilização) e a quebra de
        # perdas nomeada — só consumidos pela aba Análises (OEE). Reaproveitam
        # exatamente as mesmas bases temporais do OEE canônico, sem fórmula nova.
        utilization_ratio = (
            time_bases["worked_seconds"] / time_bases["operational_seconds"]
            if time_bases["operational_seconds"] > 0
            else None
        )
        productivity_ratio = (
            time_bases["productive_gross_seconds"] / time_bases["operational_seconds"]
            if time_bases["operational_seconds"] > 0
            else None
        )
        ae_ratio = (
            time_bases["productive_net_seconds"] / time_bases["available_seconds"]
            if time_bases["available_seconds"] > 0
            else None
        )
        extended_metrics = {
            "utilization": MetricValue(
                utilization_ratio * 100.0 if utilization_ratio is not None else None,
                DataAvailability.AVAILABLE if utilization_ratio is not None else DataAvailability.NO_RECORDS,
                "%",
                None if utilization_ratio is not None else "Não há tempo operacional no filtro para calcular a Utilização.",
            ).to_dict(),
            "productivity": MetricValue(
                productivity_ratio * 100.0 if productivity_ratio is not None else None,
                DataAvailability.AVAILABLE if productivity_ratio is not None else DataAvailability.NO_RECORDS,
                "%",
                None if productivity_ratio is not None else "Não há tempo operacional no filtro para calcular a Produtividade.",
            ).to_dict(),
            "ae": MetricValue(
                ae_ratio * 100.0 if ae_ratio is not None else None,
                DataAvailability.AVAILABLE if ae_ratio is not None else DataAvailability.NO_RECORDS,
                "%",
                None if ae_ratio is not None else "Não há tempo disponível no filtro para calcular o AE.",
            ).to_dict(),
        }
        losses_breakdown = {
            "fora_de_turno_segundos": totals[EventCategory.OUT_OF_SHIFT],
            "sem_demanda_segundos": totals[EventCategory.NO_DEMAND],
            "parada_planejada_segundos": planned_downtime_seconds,
            "parada_nao_planejada_segundos": unplanned_downtime_seconds,
            "ritmo_segundos": time_bases["performance_difference_seconds"],
            "refugo_quantidade": scrap,
            "retrabalho_quantidade": rework_qty,
        }
        resource_kpis = []
        no_demand_exception_resources = []
        for resource_input in sorted(
            resource_inputs.values(),
            key=lambda item: str(item.get("resource") or "").casefold(),
        ):
            resource_calculation = calculate_oee(
                seconds_by_category=oee_seconds_by_category(
                    resource_input["seconds"],
                    planned_downtime_seconds=resource_input["planned_downtime_seconds"],
                ),
                good_quantity=resource_input["good"],
                scrap_quantity=resource_input["scrap"],
                rework_quantity=resource_input["rework"],
                standard_run_seconds=resource_input["standard_run_seconds"],
                good_without_standard_quantity=resource_input["good_without_standard"],
                recovered_good_quantity=resource_input["recovered"]["boa"],
                recovered_scrap_quantity=resource_input["recovered"]["refugo"],
                recovered_rework_quantity=resource_input["recovered"]["retrabalho"],
            )
            if resource_calculation.is_no_demand_exception:
                no_demand_exception_resources.append(resource_input["resource"])
            resource_estimated_performance = (
                calculate_oee(
                    seconds_by_category=oee_seconds_by_category(
                        resource_input["seconds"],
                        planned_downtime_seconds=resource_input["planned_downtime_seconds"],
                    ),
                    good_quantity=resource_input["good"],
                    scrap_quantity=resource_input["scrap"],
                    rework_quantity=resource_input["rework"],
                    standard_run_seconds=resource_input["estimated_run_seconds"],
                    good_without_standard_quantity=resource_input["estimated_good_without_standard"],
                    recovered_good_quantity=resource_input["recovered"]["boa"],
                    recovered_scrap_quantity=resource_input["recovered"]["refugo"],
                    recovered_rework_quantity=resource_input["recovered"]["retrabalho"],
                ).performance
                if resource_input["good_with_estimated_standard"]
                else resource_calculation.performance
            )
            resource_kpis.append({
                "resource": resource_input["resource"],
                "sector": resource_input["sector"],
                "performance_estimada": resource_estimated_performance.to_dict(),
                "pecas_boas_tempo_estimado": resource_input["good_with_estimated_standard"],
                "metrics": resource_calculation.metrics_dict(),
                "kpi_time_bases": dict(resource_calculation.time_bases),
                "kpi_calculation": {
                    **resource_calculation.trace_dict(),
                    **self._standard_origin_trace(
                        resource_input["standard_run_seconds"],
                        resource_input["nesting_standard_seconds"],
                    ),
                },
                "calculation_policy": "canonical_oee",
            })
        simulation = None
        if self.simulation_mode:
            planned_quantity = sum(
                max(
                    0,
                    int(
                        row.get("quantidade_planejada_pcp")
                        if row.get("quantidade_planejada_pcp") is not None
                        else row.get("quantidade") or 0
                    ),
                )
                for row in facts
            )
            simulation = {
                "enabled": True,
                "reference_time": self._now(),
                "planned_quantity": planned_quantity,
                "actual_quantity": good,
                "attainment_percentage": good / planned_quantity * 100.0 if planned_quantity else None,
                "difference_quantity": good - planned_quantity,
                "time_bases": {
                    **time_bases,
                    # Fora de turno não é parada planejada: é calendário. As
                    # duas grandezas passam a viver em chaves próprias.
                    "planned_downtime_seconds": planned_downtime_seconds,
                    "unplanned_downtime_seconds": unplanned_downtime_seconds,
                    "downtime_seconds": totals[EventCategory.DOWNTIME],
                    "out_of_shift_seconds": totals[EventCategory.OUT_OF_SHIFT],
                    "no_demand_seconds": totals[EventCategory.NO_DEMAND],
                    "queue_seconds": totals[EventCategory.QUEUE],
                    "activity_without_op_seconds": totals[EventCategory.ACTIVITY_WITHOUT_OP],
                    "setup_seconds": totals[EventCategory.SETUP],
                    "rework_seconds": totals[EventCategory.REWORK],
                },
                "metrics": {
                    "availability": availability.to_dict(),
                    "performance": performance.to_dict(),
                    "ftt": ftt.to_dict(),
                    "oee": oee.to_dict(),
                    **extended_metrics,
                },
                "policy": "canonical_oee",
            }

        # OEE por setor: mesmo calculador e mesma política do consolidado
        # (SOMA_DE_BASES_SEM_DEMANDA_SEGREGADO), aplicados às bases do setor. A
        # soma das bases dos setores reproduz as bases do total.
        sector_kpis = []
        for sector, bucket in sorted(sectors.items(), key=lambda item: item[0].casefold()):
            sector_calculation = calculate_oee(
                seconds_by_category=oee_seconds_by_category(
                    bucket["seconds"],
                    planned_downtime_seconds=bucket["planned_downtime_seconds"],
                ),
                good_quantity=bucket["good"],
                scrap_quantity=bucket["scrap"],
                rework_quantity=bucket["rework"],
                standard_run_seconds=bucket["standard_run_seconds"],
                good_without_standard_quantity=bucket["good_without_standard"],
                recovered_good_quantity=bucket["recovered"]["boa"],
                recovered_scrap_quantity=bucket["recovered"]["refugo"],
                recovered_rework_quantity=bucket["recovered"]["retrabalho"],
            )
            sector_kpis.append({
                "setor": sector,
                "metrics": sector_calculation.metrics_dict(),
                "kpi_time_bases": dict(sector_calculation.time_bases),
                "kpi_calculation": {
                    **sector_calculation.trace_dict(),
                    **self._standard_origin_trace(
                        bucket["standard_run_seconds"],
                        bucket["nesting_standard_seconds"],
                    ),
                },
                "pecas_boas_sem_tempo_padrao": bucket["good_without_standard"],
                "parada_planejada_segundos": bucket["planned_downtime_seconds"],
                "calculation_policy": "canonical_oee",
            })

        sector_rows = []
        for sector, bucket in sorted(sectors.items()):
            sector_rows.append({
                "setor": sector,
                "producao_boa": bucket["good"],
                "refugo": bucket["scrap"],
                "retrabalho": bucket["rework"],
                "ops": len(bucket["ops"]),
                "tempo_producao_segundos": bucket["seconds"][EventCategory.PRODUCTION],
                "tempo_setup_segundos": bucket["seconds"][EventCategory.SETUP],
                "tempo_parada_segundos": bucket["seconds"][EventCategory.DOWNTIME],
                "tempo_retrabalho_segundos": bucket["seconds"][EventCategory.REWORK],
                "tempo_atividade_sem_op_segundos": bucket["seconds"][EventCategory.ACTIVITY_WITHOUT_OP],
                # Três leituras distintas e nomeadas. Sem o bucket de ausência
                # de demanda, esse tempo sumia da aba por setor e "fora de
                # turno" ficava sendo o único balde grande visível.
                "tempo_sem_demanda_segundos": bucket["seconds"][EventCategory.NO_DEMAND],
                "tempo_fila_segundos": bucket["seconds"][EventCategory.QUEUE],
                "tempo_fora_turno_segundos": bucket["seconds"][EventCategory.OUT_OF_SHIFT],
                "tempo_produtivo_segundos": sum(
                    bucket["seconds"][category]
                    for category in EventCategory
                    if ManufacturingRules.is_productive(category)
                ),
            })

        if nesting_rows:
            cutting_row = next((row for row in sector_rows if str(row["setor"]).casefold() == "corte"), None)
            if cutting_row is None:
                cutting_row = {
                    "setor": "Corte", "producao_boa": 0, "refugo": 0, "retrabalho": 0,
                    "ops": 0, "tempo_producao_segundos": 0.0, "tempo_setup_segundos": 0.0,
                    "tempo_parada_segundos": 0.0, "tempo_retrabalho_segundos": 0.0,
                    "tempo_atividade_sem_op_segundos": 0.0, "tempo_sem_demanda_segundos": 0.0,
                    "tempo_fila_segundos": 0.0, "tempo_fora_turno_segundos": 0.0,
                    "tempo_produtivo_segundos": 0.0,
                }
                sector_rows.append(cutting_row)
            cutting_row["nestings"] = len(nesting_rows)
            cutting_row["nestings_concluidos"] = len(completed_nestings)
            sector_rows.sort(key=lambda item: str(item.get("setor") or "").casefold())

        result = {
            "periodo": filters.to_dict(),
            "production": {
                "good": good,
                "scrap": scrap,
                "rework": rework_qty,
                # Parte de good/scrap/rework que é peça recuperada do retrabalho:
                # produção física, mas fora do FTT.
                "ftt_recovered": {
                    "good": recovered_good,
                    "scrap": recovered_scrap,
                    "rework": recovered_rework,
                },
                "ops": len(ops),
                "resources": len(resources),
                "availability": (
                    DataAvailability.AVAILABLE.value
                    if quantity_evidence
                    else DataAvailability.NO_RECORDS.value
                ),
                "reason": (
                    None
                    if quantity_evidence
                    else "Nenhum registro de quantidade foi encontrado para o período e os filtros informados."
                ),
                "source": quantity_source,
            },
            "hours": {
                "measured_seconds": measured_seconds,
                "physical_measured_seconds": measured_seconds,
                "raw_attributed_timeline_seconds": (
                    physical["raw_attributed_seconds"] + cutting_without_interval_seconds
                ),
                "overlap_removed_seconds": physical["overlap_removed_seconds"],
                "overlap_seconds": physical["overlap_seconds"],
                "conflicting_state_seconds": physical["conflicting_state_seconds"],
                "conflicting_sector_seconds": physical["conflicting_sector_seconds"],
                "production_seconds": totals[EventCategory.PRODUCTION],
                "cutting_production_seconds": cutting_physical_seconds,
                "setup_seconds": totals[EventCategory.SETUP],
                "rework_seconds": totals[EventCategory.REWORK],
                "downtime_seconds": downtime_seconds,
                "planned_downtime_seconds": planned_downtime_seconds,
                "unplanned_downtime_seconds": unplanned_downtime_seconds,
                "queue_seconds": totals[EventCategory.QUEUE],
                # Ausência de demanda: recurso em turno sem trabalho atribuído.
                # Não é fila operacional e não é fora de turno.
                "no_demand_seconds": totals[EventCategory.NO_DEMAND],
                "productive_seconds": productive_seconds,
                "activity_without_op_seconds": totals[EventCategory.ACTIVITY_WITHOUT_OP],
                # Grandeza global de calendário: o mesmo intervalo noturno visto
                # em vários setores não é somado duas vezes.
                "out_of_shift_seconds": totals[EventCategory.OUT_OF_SHIFT],
                "out_of_shift_attributed_seconds": physical["out_of_shift_attributed_seconds"],
                "out_of_shift_duplicated_seconds": physical["out_of_shift_duplicated_seconds"],
                # Divisor da média por recurso: recursos que tiveram turno/
                # calendário no período (um recurso conta uma vez, mesmo em
                # vários dias). ``day_count`` informa a extensão do período.
                "resource_count": len(consolidation["calendar_resources"]),
                # Recursos que entram na soma (fora do turno não conta). Aditivo:
                # divisor da média quando nenhum recurso tem turno cadastrado.
                "summed_resource_count": self._summed_resources(physical),
                "day_count": consolidation["days"],
                # Mesma conta, só com recursos que têm turno no período. Aditivo:
                # só o cartão "Composição do tempo" lê (decisão de 19/10/2026).
                "calendar_scope": self._calendar_scope(
                    physical,
                    consolidation["calendar_resources"],
                    cutting_without_interval_by_resource,
                    {
                        key for key, name in cutting_without_interval_names.items()
                        if self._has_shift(name, filters)
                    },
                ),
            },
            "kpis": {
                "availability": availability.to_dict(),
                "performance": performance.to_dict(),
                "ftt": ftt.to_dict(),
                "oee": oee.to_dict(),
            },
            # Performance "estimada": mesma fórmula, mas também conta o tempo
            # padrão estimado pelo Gestor (P25). Separada de `kpis` de propósito:
            # a Performance oficial só usa Protheus + manual.
            "kpis_estimados": {
                "performance": estimated_performance.to_dict(),
                "usa_tempo_estimado": bool(good_with_estimated_standard),
                "pecas_boas_tempo_estimado": good_with_estimated_standard,
            },
            "kpi_contract": dict(OEE_CONTRACT),
            "kpi_time_bases": time_bases,
            "kpi_calculation": {
                **oee_calculation.trace_dict(),
                **self._standard_origin_trace(
                    standard_run_seconds,
                    cutting_standard["standard_seconds"],
                ),
                "cutting_standard": {
                    key: value
                    for key, value in cutting_standard.items()
                    if key not in ("sheets", "tasks_with_standard")
                },
                # Recursos cujo período foi integralmente sem demanda recebem
                # 0% por convenção. No consolidado o tempo sem demanda não
                # entra nas bases, logo esse zero fica segregado.
                # Homologação completa confirmada pela manufatura (Gabriel
                # Fogaça) em 19/10/2026, regra corporativa-2026-09-24: somar
                # numeradores/denominadores e recalcular os percentuais (nunca
                # média de percentuais); tempos = ocupação física, sem duplicar
                # OPs simultâneas; recurso todo sem demanda = zero nas bases e
                # listado em "sem demanda no período"; estado desconhecido =
                # disponível não trabalhado.
                "no_demand_exception_resources": no_demand_exception_resources,
                "consolidation": "SOMA_DE_BASES_SEM_DEMANDA_SEGREGADO",
                "consolidation_status": "HOMOLOGADO",
            },
            # Só consumidos pela aba Análises (OEE) — não entram no Andon nem
            # em outras telas, que continuam lendo apenas "kpis".
            "kpis_estendidos": extended_metrics,
            "kpi_losses_breakdown": losses_breakdown,
            "resource_kpis": resource_kpis,
            "sector_kpis": sector_kpis,
            "sectors": sector_rows,
            "cutting": {
                "nestings": len(nesting_rows),
                "completed_nestings": len(completed_nestings),
                "real_seconds": cutting_real_seconds,
                "physical_seconds": cutting_physical_seconds,
                "overlap_removed_seconds": nesting_physical["overlap_removed_seconds"],
                "planned_seconds": cutting_planned_seconds,
                "items": nesting_rows,
            },
            "audit": {
                "open_issues": self._load_open_issues(filters.setor),
            },
            "data_quality": {
                "calendar_configured": calendar_available,
                "facts": len(facts),
                "physical_state_source": (
                    "eventos_estado_recurso"
                    if use_canonical_resource_state
                    else "timeline_apontamentos_fallback"
                ),
                "physical_state_rows": len(state_rows),
                "physical_time_overlap_removed_seconds": physical["overlap_removed_seconds"],
                "conflicting_state_seconds": physical["conflicting_state_seconds"],
                "conflicting_sector_seconds": physical["conflicting_sector_seconds"],
                "status": DataAvailability.PARTIAL.value,
            },
            "rateio": self._load_rateio_summary(filters),
        }
        if simulation is not None:
            result["simulation"] = simulation
        self._overview_cache[filters] = result
        return result

    @contextmanager
    def _janela_prefetch(self, filters: AnalyticsFilter, periodos=None):
        """Carrega os insumos da janela inteira uma vez e serve os buckets dela.

        Cada ponto da evolução continua passando por ``get_overview`` e pelo
        calculador canônico de ``mes/analytics/oee.py``. O que muda é apenas a
        origem das linhas: memória em vez de uma consulta por bucket.
        """

        anterior = getattr(self, "_prefetch", None)
        if anterior is not None and anterior.cobre(filters, periodos):
            # Já existe uma janela carregada para este mesmo período: reentrar
            # recarregaria tudo de novo e anularia o ganho.
            yield
            return
        self._prefetch = None
        try:
            facts = self._load_operational_facts(filters)
            quantity_available, quantity_events = self._load_quantity_events(filters)
            state_available, state_rows = self._load_resource_states(filters)
            self._prefetch = _JanelaPrefetch(
                facts=facts,
                quantity_available=quantity_available,
                quantity_events=quantity_events,
                state_available=state_available,
                state_rows=state_rows,
                agora=datetime.now().replace(microsecond=0),
                janela=(filters.inicio, filters.fim),
            )
            if periodos:
                self._prefetch.indexar(periodos)
            yield
        finally:
            self._prefetch = anterior

    def _bucket_days(self, filters: AnalyticsFilter) -> int:
        total_days = max(1, (filters.fim.date() - filters.inicio.date()).days + 1)
        return max(1, math.ceil(total_days / self._MAX_OEE_EVOLUTION_POINTS))

    def _bucket_bounds(self, filters: AnalyticsFilter) -> list[tuple[datetime, datetime]]:
        """Fronteiras dos sub-períodos da evolução, na ordem de exibição."""

        total_days = max(1, (filters.fim.date() - filters.inicio.date()).days + 1)
        bucket_days = max(1, math.ceil(total_days / self._MAX_OEE_EVOLUTION_POINTS))
        bounds = []
        cursor = filters.inicio
        while cursor < filters.fim:
            boundary = min(filters.fim, cursor + timedelta(days=bucket_days))
            # Os repositórios legados tratam ``fim`` como inclusivo em algumas
            # consultas. Um microssegundo evita contar no intervalo anterior um
            # evento que pertence exatamente ao início do próximo intervalo.
            bucket_end = (
                boundary
                if boundary >= filters.fim
                else boundary - timedelta(microseconds=1)
            )
            bounds.append((cursor, bucket_end))
            cursor = boundary
        return bounds

    @staticmethod
    def _series_availability(available_points: int, total_buckets: int) -> tuple[str, Optional[str]]:
        """Disponibilidade de uma série por intervalos (evolução e tendência)."""

        missing_points = total_buckets - available_points
        if available_points >= 2:
            if missing_points == 0:
                return DataAvailability.AVAILABLE.value, None
            return (
                DataAvailability.PARTIAL.value,
                f"Série parcial: {available_points} de {total_buckets} períodos "
                "possuem dados suficientes para o OEE.",
            )
        if available_points == 1:
            return (
                DataAvailability.INSUFFICIENT_DATA.value,
                "Apenas um período possui OEE calculável; são necessários pelo "
                "menos dois pontos para exibir a evolução.",
            )
        return (
            DataAvailability.INSUFFICIENT_DATA.value,
            "Dados insuficientes para exibir a evolução do OEE no período selecionado.",
        )

    def get_oee_evolution(self, filters: AnalyticsFilter) -> dict:
        """Monta a série temporal consumindo o mesmo OEE canônico do resumo.

        O período é dividido em no máximo 31 intervalos. Cada ponto vem de
        ``get_overview`` para o respectivo intervalo; portanto esta projeção não
        contém nem replica fórmula de OEE, Disponibilidade, Performance ou FTT.
        """

        bucket_days = self._bucket_days(filters)
        bounds = self._bucket_bounds(filters)
        points = []
        total_buckets = 0

        # Uma leitura para toda a janela, indexada pelos sub-períodos: cada
        # bucket recebe suas linhas sem voltar ao PostgreSQL e sem varrer a
        # janela inteira.
        with self._janela_prefetch(filters, periodos=bounds):
            for cursor, bucket_end in bounds:
                bucket_filter = AnalyticsFilter(
                    inicio=cursor,
                    fim=bucket_end,
                    setor=filters.setor,
                    recurso=filters.recurso,
                    turno=filters.turno,
                    op=filters.op,
                    operacao=filters.operacao,
                    produto=filters.produto,
                    operador=filters.operador,
                )
                bucket_kpis = self.get_overview(bucket_filter).get("kpis", {})
                metric = bucket_kpis.get("oee", {})
                if metric.get("value") is not None:
                    points.append({
                        "at": cursor.isoformat(),
                        "period_start": cursor.isoformat(),
                        "period_end": bucket_end.isoformat(),
                        "value": float(metric["value"]),
                        "unit": metric.get("unit") or "%",
                        "components": {
                            key: dict(bucket_kpis.get(key) or {})
                            for key in ("oee", "availability", "performance", "ftt")
                        },
                    })
                total_buckets += 1

        available_points = len(points)
        missing_points = total_buckets - available_points
        availability, reason = self._series_availability(available_points, total_buckets)

        return {
            "points": points,
            "availability": availability,
            "reason": reason,
            "bucket_days": bucket_days,
            "total_buckets": total_buckets,
            "available_points": available_points,
            "missing_points": missing_points,
            "calculation_policy": "canonical_oee",
        }

    def physical_consolidation(self, filters: AnalyticsFilter) -> dict:
        """Tempo físico consolidado do período: a mesma conta que o overview publica.

        É a fonte única para ``get_overview`` e para o serviço de explicação do
        número: quem explica usa exatamente esta consolidação, não uma segunda
        conta paralela. Retorna o resultado de ``consolidate_physical_time``
        (cujos segmentos carregam ``source_refs`` e ``rule``), os recursos que
        tiveram turno/calendário no período, a quantidade de dias e o instante
        do cálculo.
        """

        facts = self._load_operational_facts(filters)
        state_source_available, state_rows = self._load_resource_states(filters)
        nesting_inputs, without_interval = self._nesting_physical_inputs(
            self.get_nesting_times(filters), filters
        )
        result = self._consolidate_physical(
            filters,
            facts=facts,
            state_source_available=state_source_available,
            state_rows=state_rows,
            nesting_physical_inputs=nesting_inputs,
        )
        public = {key: result[key] for key in (
            "consolidated", "calendar_resources", "days", "calculated_at"
        )}
        # Insumos da explicação (aditivos, sem nova consulta): estados lidos e,
        # só na leitura legada (sem estado canônico), os nestings que o overview
        # soma à produção por conhecerem apenas a duração.
        public["state_rows"] = state_rows
        public["legacy_without_interval"] = (
            []
            if state_source_available and state_rows
            else [
                {
                    "resource": str(row.get("maquina") or "").strip(),
                    "seconds": float(
                        row.get("real_periodo_segundos", row.get("real_segundos")) or 0
                    ),
                    "has_shift": self._has_shift(
                        str(row.get("maquina") or "").strip(), filters
                    ),
                }
                for row in without_interval
            ]
        )
        return public

    @staticmethod
    def _summed_resources(physical) -> int:
        """Recursos com tempo somado no período, sem contar o fora do turno."""

        return sum(
            1
            for resource, totals in physical["by_resource"].items()
            if str(resource or "").strip().casefold() not in ("", "não informado")
            and any(
                seconds > 0
                for category, seconds in totals.items()
                if category != EventCategory.OUT_OF_SHIFT
            )
        )

    @staticmethod
    def _calendar_scope(
        physical, calendar_resources, legacy_by_resource, legacy_with_shift=frozenset()
    ) -> dict | None:
        """Horas da Visão Geral só dos recursos com turno (``None`` sem calendário).

        Não altera a consolidação compartilhada: OEE, KPIs por recurso e custos
        continuam contando todos os recursos. Nesting legado sem horário não tem
        trecho consolidado; entra se o recurso tem turno (``legacy_with_shift``).
        """

        if not calendar_resources:
            return None
        scoped = restrict_to_resources(physical, calendar_resources)
        with_calendar = {name.casefold() for name in calendar_resources} | set(legacy_with_shift)
        legacy = sum(
            seconds for key, seconds in legacy_by_resource.items() if key in with_calendar
        )
        totals = scoped["totals"]
        by_class = scoped["totals_by_stop_classification"].get(EventCategory.DOWNTIME, {})
        planned = float(by_class.get(StopClassification.PLANNED, 0.0))
        downtime = float(totals.get(EventCategory.DOWNTIME, 0.0))
        excluded: dict[str, float] = defaultdict(float)
        for segment in physical["segments"]:
            if segment.resource not in calendar_resources:
                excluded[segment.resource] += segment.seconds
        return {
            "production_seconds": float(totals.get(EventCategory.PRODUCTION, 0.0)) + legacy,
            "setup_seconds": float(totals.get(EventCategory.SETUP, 0.0)),
            "rework_seconds": float(totals.get(EventCategory.REWORK, 0.0)),
            "downtime_seconds": downtime,
            "planned_downtime_seconds": planned,
            "unplanned_downtime_seconds": max(0.0, downtime - planned),
            "no_demand_seconds": float(totals.get(EventCategory.NO_DEMAND, 0.0)),
            "activity_without_op_seconds": float(
                totals.get(EventCategory.ACTIVITY_WITHOUT_OP, 0.0)
            ),
            "conflicting_state_seconds": scoped["conflicting_state_seconds"],
            "excluded_resources": len(excluded),
            "excluded_seconds": sum(excluded.values()),
        }

    def _consolidate_physical(
        self, filters, *, facts, state_source_available, state_rows, nesting_physical_inputs
    ) -> dict:
        """Núcleo de ``physical_consolidation`` sobre insumos já carregados.

        ``get_overview`` já tem fatos, estados e nestings em mãos; passar por
        aqui evita reler o banco sem criar uma segunda conta. Além do contrato
        público devolve ``inputs`` (segmentos que entraram na consolidação).
        """

        if state_source_available and state_rows:
            # Estado físico canônico substitui as timelines por OP.
            inputs = build_physical_state_inputs(
                state_rows, inicio=filters.inicio, fim=filters.fim,
                calendar=CalendarService(self.db),
            )
        else:
            inputs = self._fact_physical_inputs(facts, filters)
            inputs.extend(nesting_physical_inputs)
        consolidated = consolidate_physical_time(inputs)
        return {
            "consolidated": consolidated,
            "calendar_resources": self._calendar_resources(consolidated, filters),
            "days": self._period_days(filters),
            "calculated_at": self._now(),
            "inputs": inputs,
        }

    def _fact_window(self, row, filters):
        """Recorte do apontamento no período, ou ``None`` se não toca o período."""

        start = _dt(row.get("data_inicio"))
        if not start:
            return None
        finish = _dt(row.get("data_fim")) or min(self._now(), filters.fim)
        clip_start = max(start, filters.inicio)
        clip_end = min(finish, filters.fim)
        if clip_end <= clip_start:
            return None
        return clip_start, clip_end

    def _fact_physical_inputs(self, facts, filters) -> list:
        """Segmentos físicos das timelines dos apontamentos (fonte de fallback)."""

        inputs = []
        for row in facts:
            window = self._fact_window(row, filters)
            if window is None:
                continue
            timeline = build_operator_timeline(
                row.get("eventos") or [], start=window[0], end=window[1]
            )
            resource = str(row.get("maquina") or "").strip()
            sector = str(row.get("tipo_setor") or "").strip() or "Não informado"
            for segment in timeline.segments:
                inputs.append(PhysicalInputSegment(
                    resource=resource or "Não informado",
                    sector=sector,
                    category=(segment.category if timeline.has_event_data else EventCategory.UNKNOWN),
                    start=segment.start,
                    end=segment.end,
                    source_ref=f"apontamento:{row.get('id')}",
                ))
        return inputs

    def _nesting_physical_inputs(self, nesting_rows, filters):
        """Nestings do Corte como segmentos físicos.

        Retorna ``(segmentos, linhas_sem_intervalo)``: as linhas sem início/fim
        válidos só conhecem a duração e ficam fora da detecção de sobreposição.
        """

        inputs = []
        without_interval = []
        for row in nesting_rows:
            start = _dt(row.get("inicio"))
            finish = _dt(row.get("fim")) or (min(self._now(), filters.fim) if start else None)
            if start and finish:
                clip_start = max(start, filters.inicio)
                clip_end = min(finish, filters.fim)
                if clip_end > clip_start:
                    inputs.append(PhysicalInputSegment(
                        resource=str(row.get("maquina") or "Não informado").strip() or "Não informado",
                        sector="Corte",
                        category=EventCategory.PRODUCTION,
                        start=clip_start,
                        end=clip_end,
                        source_ref=f"nesting:{row.get('apontamento_id')}",
                    ))
                    continue
            without_interval.append(row)
        return inputs, without_interval

    CUTTING_STANDARD_ORIGIN = "nesting_previsto"
    CUTTING_PERFORMANCE_LABEL = "Performance baseada no previsto do nesting"

    def _cutting_standard(self, nesting_rows, filters) -> dict:
        """Tempo padrão do Corte a partir do previsto do SigmaNEST (opção A).

        Regra (manufatura, 19/10/2026): padrão do plano = tempo previsto do
        plano × (chapas cortadas ÷ chapas do plano). Cada linha de
        ``apontamentos_corte`` é uma chapa física (programa + chapa +
        repetição) com o próprio ``tempo_previsto_segundos``; somar o previsto
        das chapas finalizadas no período é exatamente essa conta, sem
        depender de chapas fora da janela. Chapa em processo ainda não foi
        cortada e não credita padrão. Chapa cortada sem previsto não credita
        nada e deixa a tarefa sem padrão.
        """

        sheets = []
        tasks_seen = set()
        tasks_missing = set()
        sheets_without_standard = 0
        for row in nesting_rows:
            task = str(row.get("tarefa") or "").strip().casefold()
            if task:
                tasks_seen.add(task)
            planned = float(row.get("previsto_segundos") or 0)
            if planned <= 0 and task:
                tasks_missing.add(task)
            if str(row.get("status") or "").strip().casefold() != "finalizado":
                continue
            finished = _dt(row.get("fim"))
            if finished is None or finished < filters.inicio or finished > filters.fim:
                continue
            if planned <= 0:
                sheets_without_standard += 1
                continue
            sheets.append({
                "maquina": str(row.get("maquina") or "").strip(),
                "standard_seconds": planned,
            })
        return {
            "origin": self.CUTTING_STANDARD_ORIGIN,
            "label": self.CUTTING_PERFORMANCE_LABEL,
            "rule": (
                "padrão do plano = tempo_previsto_segundos × "
                "(chapas cortadas ÷ chapas do plano)"
            ),
            "standard_seconds": sum(item["standard_seconds"] for item in sheets),
            "cut_sheets_with_standard": len(sheets),
            "cut_sheets_without_standard": sheets_without_standard,
            "sheets": sheets,
            "tasks_with_standard": tasks_seen - tasks_missing,
        }

    @classmethod
    def _standard_origin_trace(cls, standard_seconds, nesting_seconds) -> dict:
        """Origem do S_boas no trace, com o previsto do nesting separado."""

        if not nesting_seconds:
            return {}
        other = max(0.0, float(standard_seconds or 0.0) - float(nesting_seconds))
        return {
            "standard_origin": (
                cls.CUTTING_STANDARD_ORIGIN if other <= 0 else "misto"
            ),
            "standard_origins_seconds": {
                "oficial_protheus_manual": other,
                cls.CUTTING_STANDARD_ORIGIN: float(nesting_seconds),
            },
            "performance_label": cls.CUTTING_PERFORMANCE_LABEL,
        }

    def _has_shift(self, name: str, filters) -> bool:
        """O recurso tem algum turno que toca o período."""

        return any(
            end > filters.inicio and start < filters.fim
            for start, end in CalendarService(self.db).shift_intervals(
                name, filters.inicio, filters.fim
            )
        )

    def _calendar_resources(self, consolidated, filters) -> set:
        """Recursos consolidados que tiveram turno no período.

        É o divisor da média por recurso. Um recurso entra uma vez só, tenha
        turno em um ou em vários dias do período. Recurso sem calendário
        cadastrado, ou com turnos só fora do período, não entra.
        """

        calendar = CalendarService(self.db)
        resources = set()
        for resource in consolidated["by_resource"]:
            name = str(resource or "").strip()
            if not name or name.casefold() == "não informado":
                continue
            if any(
                end > filters.inicio and start < filters.fim
                for start, end in calendar.shift_intervals(name, filters.inicio, filters.fim)
            ):
                resources.add(name)
        return resources

    @staticmethod
    def _period_days(filters) -> int:
        """Dias de calendário que o período toca; ``fim`` à meia-noite é exclusivo."""

        last = filters.fim - timedelta(microseconds=1) if filters.fim > filters.inicio else filters.inicio
        return (last.date() - filters.inicio.date()).days + 1

    def get_overview_trend(self, filters: AnalyticsFilter) -> dict:
        """Projeção de tendência da Visão Geral: pontos, período anterior e setores.

        Não existe fórmula aqui. Cada ponto, o período anterior e o período
        inteiro vêm de ``get_overview`` (OEE canônico); este método apenas
        recorta os campos e organiza a série. Todas as leituras compartilham uma
        única janela pré-carregada que cobre também o período anterior.
        """

        bucket_days = self._bucket_days(filters)
        bounds = self._bucket_bounds(filters)
        previous_bounds = self._previous_period(filters)
        window = (
            replace(filters, inicio=previous_bounds[0])
            if previous_bounds is not None
            else filters
        )

        with self._janela_prefetch(window, periodos=bounds):
            overviews = [
                self.get_overview(replace(filters, inicio=inicio, fim=fim))
                for inicio, fim in bounds
            ]
            whole = self.get_overview(filters)
            previous = (
                self.get_overview(
                    replace(filters, inicio=previous_bounds[0], fim=previous_bounds[1])
                )
                if previous_bounds is not None
                else None
            )

        points = [
            {
                "period_start": inicio.isoformat(),
                "period_end": fim.isoformat(),
                **self._trend_production_and_kpis(overview),
                "hours": {
                    key: (overview.get("hours") or {}).get(key)
                    for key in self._TREND_HOURS_KEYS
                },
                "planned_quantity": self._trend_planned_quantity(overview),
                "sectors": [
                    {
                        "setor": row.get("setor"),
                        "producao_boa": int(row.get("producao_boa") or 0),
                    }
                    for row in overview.get("sectors") or []
                ],
            }
            for (inicio, fim), overview in zip(bounds, overviews)
        ]

        available_points = sum(
            1 for point in points if point["kpis"]["oee"].get("value") is not None
        )
        availability, reason = self._series_availability(available_points, len(points))
        if available_points == 0 and self._overview_has_no_records(whole):
            availability = DataAvailability.NO_RECORDS.value
            reason = (
                "Nenhum registro de produção ou tempo foi encontrado para o "
                "período e os filtros informados."
            )

        return {
            "bucket_days": bucket_days,
            "availability": availability,
            "reason": reason,
            "points": points,
            "previous": (
                {
                    "period_start": previous_bounds[0].isoformat(),
                    "period_end": previous_bounds[1].isoformat(),
                    **self._trend_production_and_kpis(previous),
                }
                if previous is not None
                else None
            ),
            "sector_summary": self._trend_sector_summary(whole),
            "recent_events": self._load_recent_state_events(filters),
            "calculation_policy": "canonical_oee",
        }

    def _previous_period(self, filters: AnalyticsFilter) -> Optional[tuple[datetime, datetime]]:
        """Período imediatamente anterior, de mesma duração (``None`` se inválido).

        O fim recua um microssegundo, a mesma convenção de ``_bucket_bounds``,
        para que um evento exatamente em ``filters.inicio`` não conte nos dois.
        """

        duration = filters.fim - filters.inicio
        try:
            previous_start = filters.inicio - duration
        except OverflowError:
            return None
        previous_end = filters.inicio - timedelta(microseconds=1)
        if previous_start.year < self._MIN_PERIOD_YEAR or previous_end <= previous_start:
            return None
        return previous_start, previous_end

    @classmethod
    def _trend_production_and_kpis(cls, overview: dict) -> dict:
        production = overview.get("production") or {}
        kpis = overview.get("kpis") or {}
        return {
            "production": {
                key: int(production.get(key) or 0) for key in ("good", "scrap", "rework")
            },
            "kpis": {key: dict(kpis.get(key) or {}) for key in cls._TREND_KPI_KEYS},
        }

    @staticmethod
    def _trend_planned_quantity(overview: dict) -> Optional[int]:
        # Plano só existe na simulação; em produção real nada é inferido.
        simulation = overview.get("simulation")
        if not simulation or simulation.get("planned_quantity") is None:
            return None
        return int(simulation["planned_quantity"])

    @staticmethod
    def _overview_has_no_records(overview: dict) -> bool:
        production = overview.get("production") or {}
        hours = overview.get("hours") or {}
        return (
            production.get("availability") == DataAvailability.NO_RECORDS.value
            and not float(hours.get("measured_seconds") or 0.0)
        )

    @staticmethod
    def _trend_sector_summary(overview: dict) -> list[dict]:
        """Recursos e OEE por setor a partir das bases já calculadas do período inteiro.

        O OEE vem pronto de ``overview["sector_kpis"]`` (calculador canônico
        aplicado às bases do setor). Setor sem leitura publicada fica ``None``;
        nada é recalculado aqui.
        """

        sector_oee = {
            str(item.get("setor") or "").strip() or "Não informado": (
                (item.get("metrics") or {}).get("oee")
            )
            for item in overview.get("sector_kpis") or []
        }
        sectors: dict[str, dict] = {}
        for row in overview.get("sectors") or []:
            name = str(row.get("setor") or "").strip() or "Não informado"
            sectors.setdefault(name, {"resources_total": 0, "resources_with_production": 0})
        for resource in overview.get("resource_kpis") or []:
            name = str(resource.get("sector") or "").strip() or "Não informado"
            bucket = sectors.setdefault(
                name, {"resources_total": 0, "resources_with_production": 0}
            )
            bucket["resources_total"] += 1
            produced = float(
                (resource.get("kpi_time_bases") or {}).get("productive_gross_seconds") or 0.0
            )
            if produced > 0:
                bucket["resources_with_production"] += 1
        return [
            {
                "setor": name,
                "oee": dict(sector_oee[name]) if sector_oee.get(name) else None,
                **counts,
            }
            for name, counts in sorted(sectors.items(), key=lambda item: item[0].casefold())
        ]

    def _load_recent_state_events(self, filters: AnalyticsFilter) -> list[dict]:
        """Estados de recurso ainda vigentes que começaram dentro do período.

        Usa a consulta barata já existente de estados abertos (uma linha por
        recurso); não há leitura de histórico de transições.
        """

        loader = getattr(self.db, "listar_estados_recurso_atuais", None)
        if not callable(loader):
            return []
        catalog_loader = getattr(self.db, "listar_recursos_pcfactory", None)
        catalog_names = {
            str(row.get("codigo") or "").strip().casefold(): row.get("nome")
            for row in (catalog_loader() if callable(catalog_loader) else None) or []
        }
        events = []
        for row in loader(
            setor=filters.setor, recurso=filters.recurso, reference_time=filters.fim
        ) or []:
            started = _dt(row.get("data_inicio"))
            if started is None or started < filters.inicio or started > filters.fim:
                continue
            code = str(row.get("recurso") or "").strip()
            events.append({
                "resource": row.get("recurso"),
                "resource_name": resource_display_name(code, catalog_names.get(code.casefold())) or None,
                "sector": row.get("tipo_setor"),
                "state": row.get("status_nome") or row.get("categoria"),
                "at": started,
            })
        events.sort(key=lambda item: (item["at"], str(item["resource"] or "")), reverse=True)
        return [
            {**item, "at": item["at"].isoformat()}
            for item in events[: self._TREND_RECENT_EVENTS_LIMIT]
        ]

    @staticmethod
    def _cutting_filters_supported(filters: AnalyticsFilter) -> bool:
        """A fonte de Corte só filtra com segurança por período e recurso.

        Ela não possui vínculo direto suficiente para recortar por
        OP/operação/produto/turno/operador; nesses casos, retornar vazio é
        preferível a misturar execução não relacionada.
        """

        if filters.setor and str(filters.setor).strip().casefold() != "corte":
            return False
        return not any(
            (filters.op, filters.operacao, filters.produto, filters.turno, filters.operador)
        )

    def get_cutting_production(self, filters: AnalyticsFilter) -> list[dict]:
        """Quantidade produzida pelo Corte por OP, por execução real."""

        if not self._cutting_filters_supported(filters):
            return []
        loader = getattr(self.db, "listar_producao_corte_periodo", None)
        if not callable(loader):
            return []
        return list(
            loader(filters.inicio, filters.fim, maquina=filters.recurso) or []
        )

    def get_nesting_times(self, filters: AnalyticsFilter) -> list[dict]:
        if not self._cutting_filters_supported(filters):
            return []
        loader = getattr(self.db, "listar_tempos_nesting_corte", None)
        if not callable(loader):
            return []
        return loader(
            inicio=filters.inicio,
            fim=filters.fim,
            maquina=filters.recurso,
        )

    def _load_quantity_events(self, filters):
        prefetch = getattr(self, "_prefetch", None)
        if prefetch is not None and prefetch.quantity_sliceable:
            return prefetch.quantity_events(filters.inicio, filters.fim)
        loader = getattr(self.db, "listar_eventos_quantidade_periodo", None)
        if not callable(loader):
            return False, []
        rows = loader(
            filters.inicio, filters.fim, setor=filters.setor, recurso=filters.recurso,
            op=filters.op, operacao=filters.operacao, produto=filters.produto,
            operador=filters.operador,
        )
        return True, list(rows or [])

    def quantity_sources(self, filters: AnalyticsFilter) -> dict:
        """Linhas de quantidade que ``get_overview`` soma (insumo da explicação de valor).

        Mesma leitura do overview: eventos de quantidade do período e, só quando
        a fonte de eventos não existe, os apontamentos que tocam o período
        (fallback). A produção do Corte vem à parte, como no overview.
        """

        available, events = self._load_quantity_events(filters)
        facts = []
        if not available:
            facts = [
                row for row in self._load_operational_facts(filters)
                if self._fact_window(row, filters) is not None
            ]
        return {
            "available": available,
            "events": events,
            "facts": facts,
            "cutting": self.get_cutting_production(filters),
        }

    def _prefetch_memo(self, key, compute):
        """Leituras que não dependem do sub-período são feitas uma vez por janela."""

        prefetch = getattr(self, "_prefetch", None)
        if prefetch is None:
            return compute()
        if key not in prefetch.memo:
            prefetch.memo[key] = compute()
        return prefetch.memo[key]

    def _load_open_issues(self, setor=None):
        loader = getattr(self.db, "listar_inconsistencias_dados", None)
        if not callable(loader):
            return []
        issues = self._prefetch_memo(
            "open_issues", lambda: list(loader(somente_abertas=True) or [])
        )
        if not setor:
            return issues
        # A tabela não grava setor: a inconsistência é do setor dono do recurso.
        # Sem recurso identificável ela fica fora do filtro (nunca vaza).
        wanted = str(setor).strip().casefold()
        return [issue for issue in issues if _resource_sector(issue.get("recurso")).casefold() == wanted]

    def _load_operational_facts(self, filters):
        prefetch = getattr(self, "_prefetch", None)
        if prefetch is not None and prefetch.facts_sliceable:
            return prefetch.facts(filters.inicio, filters.fim)
        loader = getattr(self.db, "listar_fatos_operacionais_periodo", None)
        if callable(loader):
            return loader(
                filters.inicio,
                filters.fim,
                setor=filters.setor,
                recurso=filters.recurso,
                op=filters.op,
                operacao=filters.operacao,
                produto=filters.produto,
                operador=filters.operador,
            )
        # Compatibilidade com fakes/versões antigas: carrega por setor quando possível.
        if filters.setor and hasattr(self.db, "listar_apontamentos_operacionais_periodo"):
            rows = self.db.listar_apontamentos_operacionais_periodo(filters.setor, filters.inicio, filters.fim)
            event_loader = getattr(self.db, "listar_eventos_apontamento_operador", None)
            result = []
            for row in rows:
                item = dict(row)
                item["eventos"] = event_loader(item["id"]) if callable(event_loader) else []
                result.append(item)
            return result
        return []


    def _load_resource_states(self, filters):
        prefetch = getattr(self, "_prefetch", None)
        if prefetch is not None and prefetch.state_sliceable:
            return prefetch.state_rows(filters.inicio, filters.fim)
        loader = getattr(self.db, "listar_estados_recurso_periodo", None)
        if not callable(loader):
            return False, []
        rows = loader(
            filters.inicio,
            filters.fim,
            setor=filters.setor,
            recurso=filters.recurso,
            op=filters.op,
            operacao=filters.operacao,
        )
        return True, list(rows or [])


    def _load_rateio_summary(self, filters):
        loader = getattr(self.db, "listar_rateios_tempo_periodo", None)
        if not callable(loader):
            return {
                "availability": DataAvailability.NOT_CONFIGURED.value,
                "physical_seconds": 0.0,
                "attributed_seconds": 0.0,
                "conservation_ok": None,
                "sessions": [],
                "reason": "Repository atual ainda não expõe sessões físicas/rateios para leitura.",
            }
        rows = list(loader(
            filters.inicio, filters.fim,
            setor=filters.setor, recurso=filters.recurso, op=filters.op,
            operacao=filters.operacao,
        ) or [])
        physical = sum(float(row.get("segundos_fisicos_periodo") or 0) for row in rows)
        attributed = sum(
            sum(float(item.get("segundos_atribuidos_periodo") or 0) for item in (row.get("rateios") or []))
            for row in rows
        )
        return {
            "availability": (
                DataAvailability.AVAILABLE.value if rows else DataAvailability.PARTIAL.value
            ),
            "physical_seconds": physical,
            "attributed_seconds": attributed,
            "conservation_ok": (
                abs(physical - attributed) <= 0.05
                if rows and not filters.op and filters.operacao is None
                else None
            ),
            "sessions": rows,
            "reason": (
                "Tempo físico do recurso permanece separado do tempo atribuído às OPs. "
                "A soma atribuída deve conservar o tempo físico da sessão."
            ),
        }

    def _has_calendar_configuration(self, filters):
        checker = getattr(self.db, "possui_calendario_produtivo", None)
        if not callable(checker):
            return False
        return self._prefetch_memo(
            ("calendar", filters.setor, filters.recurso),
            lambda: bool(checker(filters.setor, filters.recurso)),
        )


class _JanelaPrefetch:
    """Insumos da janela inteira, fatiados em memória por sub-período.

    Existe apenas para eliminar round-trips: cada fatia reproduz exatamente o
    predicado temporal da consulta SQL correspondente, e o resultado alimenta o
    mesmo ``get_overview`` de sempre. Nenhuma métrica é calculada aqui.
    """

    def __init__(self, *, facts, quantity_available, quantity_events, state_available, state_rows, agora, janela=None):
        self.memo = {}
        self._facts = list(facts or [])
        self._quantity_available = bool(quantity_available)
        self._quantity_events = list(quantity_events or [])
        self._state_available = bool(state_available)
        self._state_rows = list(state_rows or [])
        # Congela o "agora" para que todas as fatias enxerguem o mesmo instante,
        # como CURRENT_TIMESTAMP dentro de uma única consulta.
        self._agora = agora
        # Uma fatia em memória só é fiel se toda linha trouxer o carimbo
        # temporal usado pelo predicado. Repositórios que não o publicam
        # continuam sendo consultados por bucket.
        self.facts_sliceable = all(
            _dt(row.get("data_inicio")) or _dt(row.get("data_entrada"))
            for row in self._facts
        )
        self.quantity_sliceable = all(
            _dt(row.get("data_hora")) is not None for row in self._quantity_events
        )
        self.state_sliceable = all(
            _dt(row.get("data_inicio")) is not None for row in self._state_rows
        )
        # Índice por sub-período: cada linha é visitada uma vez e cai apenas nos
        # buckets que realmente toca. Sem isto, cada bucket varreria a janela
        # inteira e o ganho de round-trip seria devorado pelo custo em memória.
        self._indice_facts: dict | None = None
        self._indice_quantidade: dict | None = None
        self._indice_estados: dict | None = None
        self.janela = janela

    def cobre(self, filters, periodos):
        """Diz se esta janela já atende o pedido, evitando recarregar tudo."""

        if self.janela != (filters.inicio, filters.fim):
            return False
        if not periodos:
            return True
        if self._indice_facts is None:
            return False
        return all(
            (self._limite(i), self._limite(f)) in self._indice_facts for i, f in periodos
        )

    def indexar(self, periodos):
        """Distribui as linhas da janela entre os sub-períodos informados.

        Os sub-períodos da evolução são contíguos e de mesma largura, então a
        posição de um instante é calculada por aritmética. Varrer a lista de
        buckets para cada linha custaria O(linhas × buckets) e devoraria o
        ganho de round-trip — a janela de três meses tem quase 30 mil estados.
        """

        # Um período repetido (janela de um dia: o resumo e o único bucket da
        # evolução são o mesmo intervalo) anexaria cada linha duas vezes ao
        # mesmo bucket; deduplica preservando a ordem.
        chaves = list(dict.fromkeys(
            (self._limite(i), self._limite(f)) for i, f in periodos
        ))
        self._indice_facts = {chave: [] for chave in chaves}
        self._indice_quantidade = {chave: [] for chave in chaves}
        self._indice_estados = {chave: [] for chave in chaves}
        if not chaves:
            return

        # Sub-períodos contíguos de largura fixa permitem localizar o bucket
        # diretamente; qualquer outro arranjo cai na varredura completa.
        contiguos = sorted({chave for chave in chaves}, key=lambda c: c[0])
        origem = contiguos[0][0]
        larguras = {
            (contiguos[i + 1][0] - contiguos[i][0]).total_seconds()
            for i in range(len(contiguos) - 1)
        }
        passo = larguras.pop() if len(larguras) == 1 else None
        if passo is not None and passo <= 0:
            passo = None

        def candidatos(inicio_row, fim_row):
            """Buckets que podem conter o intervalo, já filtrados."""

            if passo is None:
                return chaves
            primeiro = int((inicio_row - origem).total_seconds() // passo)
            ultimo = int((fim_row - origem).total_seconds() // passo)
            primeiro = max(0, min(primeiro, len(contiguos) - 1))
            ultimo = max(0, min(ultimo, len(contiguos) - 1))
            if ultimo < primeiro:
                primeiro, ultimo = ultimo, primeiro
            # Uma folga de um bucket cobre bordas e o último intervalo, que é
            # inclusivo e um pouco mais largo que os demais.
            baixo = max(0, primeiro - 1)
            alto = min(len(contiguos) - 1, ultimo + 1)
            return contiguos[baixo:alto + 1]

        if self.facts_sliceable:
            for row in self._facts:
                comeco = _dt(row.get("data_inicio")) or _dt(row.get("data_entrada"))
                termino = _dt(row.get("data_fim")) or self._agora
                if comeco is None or termino is None:
                    continue
                for chave in candidatos(comeco, termino):
                    if comeco <= chave[1] and termino >= chave[0]:
                        self._indice_facts[chave].append(row)

        if self.quantity_sliceable:
            for row in self._quantity_events:
                momento = _dt(row.get("data_hora"))
                if momento is None:
                    continue
                for chave in candidatos(momento, momento):
                    if chave[0] <= momento <= chave[1]:
                        self._indice_quantidade[chave].append(row)

        if self.state_sliceable:
            derivados = any(
                "inicio_periodo" in row or "fim_periodo" in row for row in self._state_rows
            )
            for row in self._state_rows:
                comeco = _dt(row.get("data_inicio"))
                if comeco is None:
                    continue
                bruto_fim = _dt(row.get("data_fim"))
                # Estado aberto entra em todo bucket a partir do início
                # (``COALESCE(data_fim, fim) > inicio``), não só no primeiro.
                for chave in candidatos(comeco, bruto_fim or contiguos[-1][1]):
                    inicio, fim = chave
                    if fim <= inicio or comeco >= fim:
                        continue
                    if (bruto_fim or fim) <= inicio:
                        continue
                    self._indice_estados[chave].append(
                        self._recortar_estado(row, comeco, bruto_fim, inicio, fim, self._agora)
                        if derivados else row
                    )

    @staticmethod
    def _recortar_estado(row, comeco, bruto_fim, inicio, fim, agora):
        """Mesmo recorte de ``listar_estados_recurso_periodo``.

        A inclusão do estado usa ``fim``; o tempo dele, porém, vai só até
        ``min(fim, agora)``, aberto ou fechado — senão o resto do dia seria
        contado antes de acontecer.
        """

        limite = min(fim, agora) if agora is not None else fim
        termino = bruto_fim or limite
        recorte = dict(row)
        recorte["inicio_periodo"] = max(comeco, inicio)
        recorte["fim_periodo"] = min(termino, limite)
        recorte["segundos_periodo"] = max(
            0.0,
            (recorte["fim_periodo"] - recorte["inicio_periodo"]).total_seconds(),
        )
        return recorte

    @staticmethod
    def _limite(value):
        """Mesma normalização de ``normalizar_data_db``: segundos inteiros.

        Sem isto, um ``bucket_end`` com ``.999999`` selecionaria em memória
        linhas que a consulta SQL — que recebe o limite truncado — descarta.
        """

        return value.replace(microsecond=0) if isinstance(value, datetime) else value

    def facts(self, inicio, fim):
        # SQL: COALESCE(data_inicio, data_entrada) <= fim
        #      AND COALESCE(data_fim, CURRENT_TIMESTAMP) >= inicio
        inicio = self._limite(inicio)
        fim = self._limite(fim)
        if self._indice_facts is not None and (inicio, fim) in self._indice_facts:
            return self._indice_facts[(inicio, fim)]
        resultado = []
        for row in self._facts:
            comeco = _dt(row.get("data_inicio")) or _dt(row.get("data_entrada"))
            termino = _dt(row.get("data_fim")) or self._agora
            if comeco is None or termino is None:
                continue
            if comeco <= fim and termino >= inicio:
                resultado.append(row)
        return resultado

    def quantity_events(self, inicio, fim):
        # SQL: data_hora >= inicio AND data_hora <= fim
        if not self._quantity_available:
            return False, []
        inicio = self._limite(inicio)
        fim = self._limite(fim)
        if self._indice_quantidade is not None and (inicio, fim) in self._indice_quantidade:
            return True, self._indice_quantidade[(inicio, fim)]
        resultado = []
        for row in self._quantity_events:
            momento = _dt(row.get("data_hora"))
            if momento is not None and inicio <= momento <= fim:
                resultado.append(row)
        return True, resultado

    def state_rows(self, inicio, fim):
        # SQL: data_inicio < fim AND COALESCE(data_fim, fim) > inicio,
        # precedido da guarda que devolve vazio para período não positivo.
        if not self._state_available:
            return False, []
        inicio = self._limite(inicio)
        fim = self._limite(fim)
        if self._indice_estados is not None and (inicio, fim) in self._indice_estados:
            return True, self._indice_estados[(inicio, fim)]
        if fim is None or inicio is None or fim <= inicio:
            return True, []
        resultado = []
        for row in self._state_rows:
            comeco = _dt(row.get("data_inicio"))
            if comeco is None or comeco >= fim:
                continue
            bruto_fim = _dt(row.get("data_fim"))
            if (bruto_fim or fim) <= inicio:
                continue
            if "inicio_periodo" in row or "fim_periodo" in row:
                # A consulta deriva estes campos em função do período pedido; a
                # fatia recalcula para o sub-período, senão o tempo físico do
                # bucket herdaria o recorte da janela inteira. Repositórios que
                # não publicam esses campos mantêm o formato original.
                resultado.append(
                    self._recortar_estado(row, comeco, bruto_fim, inicio, fim, self._agora)
                )
            else:
                resultado.append(row)
        return True, resultado


def _resource_sector(recurso) -> str:
    """Setor dono do recurso: associação oficial, senão o posto de apontamento."""

    code = resolve_resource_identity(recurso)
    if not code:
        return ""
    official = resource_canonical_sector(code)
    if official:
        return official
    key = code.casefold()
    return next(
        (sector.name for sector in OPERATOR_SECTORS
         if any(resolve_resource_identity(station).casefold() == key for station in sector.resources)),
        "",
    )


def _dt(value) -> Optional[datetime]:
    if value is None or isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def _good_quantity_in_period(fact, inicio, fim) -> Optional[int]:
    """Peças boas do apontamento lançadas dentro de ``[inicio, fim]``.

    Cada evento do operador com ``quantidade_boa`` gera, no mesmo instante, o
    evento canônico ``boa`` de ``eventos_quantidade_producao``; somar os
    eventos do fato com o mesmo predicado da consulta de quantidade mantém
    ``S_boas`` e "sem padrão" na mesma base das peças boas do período.
    Fatos cujos eventos não trazem quantidade (fontes legadas) devolvem
    ``None``: quem chama mantém o total do apontamento.
    """

    events = [
        event for event in (fact.get("eventos") or [])
        if isinstance(event, dict) and "quantidade_boa" in event
    ]
    if not events:
        return None
    # Mesma normalização de segundos inteiros que a consulta recebe.
    inicio = _JanelaPrefetch._limite(inicio)
    fim = _JanelaPrefetch._limite(fim)
    total = 0
    for event in events:
        moment = _dt(event.get("data_hora"))
        if moment is not None and inicio <= moment <= fim:
            total += max(0, int(event.get("quantidade_boa") or 0))
    return total
