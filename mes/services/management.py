"""Serviços gerenciais independentes da camada de apresentação.

A camada expõe dados estruturados e marca explicitamente quando uma métrica
não pode ser calculada. Isso evita que o frontend Web interprete
"ausência de dado" como zero.
"""

import math
from collections import defaultdict
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Optional

from mes.analytics.physical_time import PhysicalInputSegment, consolidate_physical_time
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


class ManagementService:
    _MAX_OEE_EVOLUTION_POINTS = 31

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
        physical_inputs = []
        good = scrap = rework_qty = 0
        standard_run_seconds = 0.0
        resources = set()
        ops = set()
        sectors = defaultdict(lambda: {"good": 0, "scrap": 0, "rework": 0, "seconds": defaultdict(float), "ops": set()})
        resource_inputs = defaultdict(lambda: {
            "resource": None,
            "sector": None,
            "good": 0,
            "scrap": 0,
            "rework": 0,
            "standard_run_seconds": 0.0,
            "seconds": defaultdict(float),
            "planned_downtime_seconds": 0.0,
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
            start = _dt(row.get("data_inicio"))
            if not start:
                continue
            finish = _dt(row.get("data_fim")) or min(self._now(), filters.fim)
            clip_start = max(start, filters.inicio)
            clip_end = min(finish, filters.fim)
            if clip_end <= clip_start:
                continue
            events = row.get("eventos") or []
            resource = str(row.get("maquina") or "").strip()
            op = str(row.get("op") or "").strip()
            sector = str(row.get("tipo_setor") or "").strip() or "Não informado"
            timeline = build_operator_timeline(events, start=clip_start, end=clip_end)
            for segment in timeline.segments:
                physical_inputs.append(PhysicalInputSegment(
                    resource=resource or "Não informado",
                    sector=sector,
                    category=(segment.category if timeline.has_event_data else EventCategory.UNKNOWN),
                    start=segment.start,
                    end=segment.end,
                    source_ref=f"apontamento:{row.get('id')}",
                ))
            if not quantity_source_available:
                good += int(row.get("quantidade_boa") or 0)
                scrap += int(row.get("quantidade_refugo") or 0)
                rework_qty += int(row.get("quantidade_retrabalho") or 0)
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
            standard_unit_seconds = row.get("tempo_medio_segundos")
            if standard_unit_seconds is not None:
                row_standard_run_seconds = max(0.0, float(standard_unit_seconds)) * max(
                    0,
                    int(row.get("quantidade_boa") or 0),
                )
                standard_run_seconds += row_standard_run_seconds
                if resource:
                    resource_bucket(resource, sector)["standard_run_seconds"] += row_standard_run_seconds
            if not quantity_source_available:
                bucket["good"] += int(row.get("quantidade_boa") or 0)
                bucket["scrap"] += int(row.get("quantidade_refugo") or 0)
                bucket["rework"] += int(row.get("quantidade_retrabalho") or 0)
            if op:
                bucket["ops"].add(op)

        state_source_available, state_rows = self._load_resource_states(filters)
        use_canonical_resource_state = bool(state_source_available and state_rows)
        if use_canonical_resource_state:
            physical_inputs = build_physical_state_inputs(
                state_rows,
                inicio=filters.inicio,
                fim=filters.fim,
            )
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
        if cutting_production:
            quantity_evidence = True

        nesting_physical_inputs = []
        cutting_without_interval_seconds = 0.0
        cutting_without_interval_by_resource = defaultdict(float)
        for row in nesting_rows:
            start = _dt(row.get("inicio"))
            finish = _dt(row.get("fim")) or (min(self._now(), filters.fim) if start else None)
            if start and finish:
                clip_start = max(start, filters.inicio)
                clip_end = min(finish, filters.fim)
                if clip_end > clip_start:
                    item = PhysicalInputSegment(
                        resource=str(row.get("maquina") or "Não informado").strip() or "Não informado",
                        sector="Corte",
                        category=EventCategory.PRODUCTION,
                        start=clip_start,
                        end=clip_end,
                        source_ref=f"nesting:{row.get('apontamento_id')}",
                    )
                    nesting_physical_inputs.append(item)
                    if not use_canonical_resource_state:
                        physical_inputs.append(item)
                    continue
            # Compatibilidade com fontes antigas que conhecem a duração, mas não
            # fornecem início/fim. Sem intervalo não é possível detectar sobreposição.
            if not use_canonical_resource_state:
                legacy_seconds = float(
                    row.get("real_periodo_segundos", row.get("real_segundos")) or 0
                )
                cutting_without_interval_seconds += legacy_seconds
                machine = str(row.get("maquina") or "").strip()
                if machine:
                    cutting_without_interval_by_resource[machine.casefold()] += legacy_seconds
                    resource_bucket(machine, "Corte")

        physical = consolidate_physical_time(physical_inputs)
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
        unplanned_downtime_seconds = float(
            downtime_by_classification.get(StopClassification.UNPLANNED, 0.0)
        )
        resource_planned_downtime = {
            resource: float(
                categories.get(EventCategory.DOWNTIME, {}).get(
                    StopClassification.PLANNED, 0.0
                )
            )
            for resource, categories in physical["by_resource_stop_classification"].items()
        }

        for resource, category_totals in physical["by_resource"].items():
            bucket = resource_bucket(resource)
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
        )
        availability = oee_calculation.availability
        performance = oee_calculation.performance
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
            )
            resource_kpis.append({
                "resource": resource_input["resource"],
                "sector": resource_input["sector"],
                "metrics": resource_calculation.metrics_dict(),
                "kpi_time_bases": dict(resource_calculation.time_bases),
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
            },
            "kpis": {
                "availability": availability.to_dict(),
                "performance": performance.to_dict(),
                "ftt": ftt.to_dict(),
                "oee": oee.to_dict(),
            },
            "kpi_contract": dict(OEE_CONTRACT),
            "kpi_time_bases": time_bases,
            # Só consumidos pela aba Análises (OEE) — não entram no Andon nem
            # em outras telas, que continuam lendo apenas "kpis".
            "kpis_estendidos": extended_metrics,
            "kpi_losses_breakdown": losses_breakdown,
            "resource_kpis": resource_kpis,
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
                "open_issues": self._load_open_issues(),
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
        if available_points >= 2:
            availability = (
                DataAvailability.AVAILABLE.value
                if missing_points == 0
                else DataAvailability.PARTIAL.value
            )
            reason = (
                None
                if missing_points == 0
                else (
                    f"Série parcial: {available_points} de {total_buckets} períodos "
                    "possuem dados suficientes para o OEE."
                )
            )
        elif available_points == 1:
            availability = DataAvailability.INSUFFICIENT_DATA.value
            reason = (
                "Apenas um período possui OEE calculável; são necessários pelo "
                "menos dois pontos para exibir a evolução."
            )
        else:
            availability = DataAvailability.INSUFFICIENT_DATA.value
            reason = "Dados insuficientes para exibir a evolução do OEE no período selecionado."

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

    def _load_open_issues(self):
        loader = getattr(self.db, "listar_inconsistencias_dados", None)
        return list(loader(somente_abertas=True) or []) if callable(loader) else []

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
        return bool(checker(filters.setor, filters.recurso)) if callable(checker) else False


class _JanelaPrefetch:
    """Insumos da janela inteira, fatiados em memória por sub-período.

    Existe apenas para eliminar round-trips: cada fatia reproduz exatamente o
    predicado temporal da consulta SQL correspondente, e o resultado alimenta o
    mesmo ``get_overview`` de sempre. Nenhuma métrica é calculada aqui.
    """

    def __init__(self, *, facts, quantity_available, quantity_events, state_available, state_rows, agora, janela=None):
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

        chaves = [(self._limite(i), self._limite(f)) for i, f in periodos]
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
                for chave in candidatos(comeco, bruto_fim or comeco):
                    inicio, fim = chave
                    if fim <= inicio or comeco >= fim:
                        continue
                    termino = bruto_fim or fim
                    if termino <= inicio:
                        continue
                    self._indice_estados[chave].append(
                        self._recortar_estado(row, comeco, termino, inicio, fim)
                        if derivados else row
                    )

    @staticmethod
    def _recortar_estado(row, comeco, termino, inicio, fim):
        recorte = dict(row)
        recorte["inicio_periodo"] = max(comeco, inicio)
        recorte["fim_periodo"] = min(termino, fim)
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
            termino = _dt(row.get("data_fim")) or fim
            if termino <= inicio:
                continue
            if "inicio_periodo" in row or "fim_periodo" in row:
                # A consulta deriva estes campos em função do período pedido; a
                # fatia recalcula para o sub-período, senão o tempo físico do
                # bucket herdaria o recorte da janela inteira. Repositórios que
                # não publicam esses campos mantêm o formato original.
                recorte = dict(row)
                recorte["inicio_periodo"] = max(comeco, inicio)
                recorte["fim_periodo"] = min(termino, fim)
                recorte["segundos_periodo"] = max(
                    0.0,
                    (recorte["fim_periodo"] - recorte["inicio_periodo"]).total_seconds(),
                )
                resultado.append(recorte)
            else:
                resultado.append(row)
        return True, resultado


def _dt(value) -> Optional[datetime]:
    if value is None or isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
