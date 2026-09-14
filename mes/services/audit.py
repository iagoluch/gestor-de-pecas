"""Auditoria canônica de inconsistências consumida pela Web.

A auditoria prefere fatos observáveis. Quando não há evidência suficiente, o
resultado é marcado como lacuna/conflito; não existe tentativa de "corrigir" a
fábrica por inferência.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from mes.analytics.physical_time import PhysicalInputSegment, consolidate_physical_time
from mes.analytics.timeline import build_operator_timeline
from mes.domain import EventCategory, IssueSeverity, ManufacturingRules
from mes.services.calendar import CalendarService


class AuditService:
    def __init__(self, db=None, now_func=None):
        self.db = db
        self._now = now_func or datetime.now

    def inspect_operational_rows(self, rows):
        issues = []
        for raw in rows or ():
            row = dict(raw)
            status = row.get("status")
            resource = str(row.get("maquina") or "").strip()
            if status == "Finalizado" and int(row.get("quantidade_boa") or 0) <= 0:
                issues.append(self._issue(
                    "producao_sem_quantidade_boa",
                    IssueSeverity.ERROR,
                    "Apontamento finalizado sem quantidade de peças boas.",
                    row,
                ))
            if status in {"Em processo", "Parada", "Setup", "Retrabalho"} and not row.get("operador_inicio"):
                issues.append(self._issue(
                    "op_sem_operador",
                    IssueSeverity.ERROR,
                    "OP ativa sem operador de início identificado.",
                    row,
                ))
            if status in {"Em processo", "Parada", "Setup", "Retrabalho"} and not resource:
                issues.append(self._issue(
                    "op_sem_recurso",
                    IssueSeverity.CRITICAL,
                    "OP ativa sem recurso identificado.",
                    row,
                ))
            if row.get("operador_inicio") and not resource:
                issues.append(self._issue(
                    "operador_sem_recurso",
                    IssueSeverity.ERROR,
                    "Operador identificado em apontamento sem recurso.",
                    row,
                ))
            if status in {"Em processo", "Parada", "Setup", "Retrabalho"} and not str(row.get("op") or "").strip():
                issues.append(self._issue(
                    "recurso_ativo_sem_op",
                    IssueSeverity.ERROR,
                    "Execução ativa de recurso sem OP identificada.",
                    row,
                ))
            start = _dt(row.get("data_inicio"))
            end = _dt(row.get("data_fim"))
            if start and end and end < start:
                issues.append(self._issue(
                    "intervalo_invalido",
                    IssueSeverity.CRITICAL,
                    "Fim do apontamento anterior ao início.",
                    row,
                ))
        return issues

    def inspect_timeline_conflicts(self, rows, *, inicio=None, fim=None):
        """Fallback histórico: detecta conflito físico em timelines por OP.

        Duas OPs simultâneas em Produção são válidas; estados distintos no mesmo
        recurso/instante são inconsistentes até que exista evidência física melhor.
        """

        inputs = []
        for raw in rows or ():
            row = dict(raw)
            start = _dt(row.get("data_inicio"))
            if start is None:
                continue
            end = _dt(row.get("data_fim")) or _dt(fim) or self._now().replace(microsecond=0)
            if inicio is not None:
                start = max(start, _dt(inicio) or start)
            if fim is not None:
                end = min(end, _dt(fim) or end)
            if end <= start:
                continue
            timeline = build_operator_timeline(row.get("eventos") or [], start=start, end=end)
            if not timeline.has_event_data:
                continue
            resource = str(row.get("maquina") or "").strip()
            if not resource:
                continue
            sector = str(row.get("tipo_setor") or "Não informado").strip() or "Não informado"
            for segment in timeline.segments:
                inputs.append(PhysicalInputSegment(
                    resource=resource,
                    sector=sector,
                    category=segment.category,
                    start=segment.start,
                    end=segment.end,
                    source_ref=f"apontamento:{row.get('id')}",
                ))

        physical = consolidate_physical_time(inputs)
        issues = []
        for segment in physical["segments"]:
            if segment.state_conflict:
                issues.append({
                    "type": "sobreposicao_estados_incompativeis",
                    "severity": IssueSeverity.CRITICAL.value,
                    "message": f"Recurso {segment.resource} possui estados físicos incompatíveis no mesmo intervalo.",
                    "appointment_id": None,
                    "op": None,
                    "operation": None,
                    "resource": segment.resource,
                    "sector": segment.sector,
                    "start": segment.start,
                    "end": segment.end,
                    "seconds": segment.seconds,
                    "source": "timeline_apontamentos_fallback",
                })
            if segment.sector_conflict:
                issues.append({
                    "type": "recurso_em_setores_conflitantes",
                    "severity": IssueSeverity.CRITICAL.value,
                    "message": f"Recurso {segment.resource} aparece em setores diferentes no mesmo intervalo.",
                    "appointment_id": None,
                    "op": None,
                    "operation": None,
                    "resource": segment.resource,
                    "sector": "Não informado",
                    "start": segment.start,
                    "end": segment.end,
                    "seconds": segment.seconds,
                    "source": "timeline_apontamentos_fallback",
                })
        return issues

    def inspect_resource_states(self, states, facts=None):
        """Audita a timeline física persistida contra OPs observadas."""

        issues = []
        facts = [dict(row) for row in (facts or ())]
        facts_by_resource = {}
        for fact in facts:
            key = str(fact.get("maquina") or "").strip().casefold()
            if key:
                facts_by_resource.setdefault(key, []).append(fact)
        for raw in states or ():
            row = dict(raw)
            category = str(row.get("categoria") or "").strip()
            start = _dt(row.get("inicio_periodo") or row.get("data_inicio"))
            end = _dt(row.get("fim_periodo") or row.get("data_fim")) or self._now()
            resource = str(row.get("recurso") or "").strip()
            if category == EventCategory.UNKNOWN.value:
                issues.append({
                    "type": "estado_fisico_desconhecido",
                    "severity": IssueSeverity.CRITICAL.value,
                    "message": "Estado físico do recurso ficou desconhecido por conflito ou falta de evidência.",
                    "appointment_id": row.get("apontamento_id"),
                    "op": row.get("op"),
                    "operation": row.get("numero_operacao"),
                    "resource": resource,
                    "sector": row.get("tipo_setor"),
                    "start": start,
                    "end": end,
                    "seconds": max(0.0, (end - start).total_seconds()) if start and end else None,
                    "source": "eventos_estado_recurso",
                })
            if category == EventCategory.PRODUCTION.value and start and end:
                overlapping = [
                    fact for fact in facts_by_resource.get(resource.casefold(), ())
                    if str(fact.get("op") or "").strip()
                    and _overlaps(
                        start,
                        end,
                        _dt(fact.get("data_inicio")),
                        _dt(fact.get("data_fim")) or end,
                    )
                ]
                # Corte/Nesting possui sua própria entidade e pode não ter OP
                # direta; só acusa ausência de OP fora de Corte.
                if not overlapping and str(row.get("tipo_setor") or "").strip().casefold() != "corte":
                    issues.append({
                        "type": "recurso_produzindo_sem_op",
                        "severity": IssueSeverity.ERROR.value,
                        "message": "Recurso em Produção sem OP operacional sobreposta no mesmo intervalo.",
                        "appointment_id": row.get("apontamento_id"),
                        "op": row.get("op"),
                        "operation": row.get("numero_operacao"),
                        "resource": resource,
                        "sector": row.get("tipo_setor"),
                        "start": start,
                        "end": end,
                        "seconds": max(0.0, (end - start).total_seconds()),
                        "source": "eventos_estado_recurso",
                    })
        return issues

    def inspect_shift_boundaries(self, rows, *, inicio, fim):
        """Valida a regra oficial 17:30/21:30 sem usar regra do PCFactory."""

        issues = []
        start_period = _dt(inicio)
        end_period = _dt(fim)
        if not start_period or not end_period:
            return issues
        for raw in rows or ():
            row = dict(raw)
            start = _dt(row.get("data_inicio"))
            if not start:
                continue
            row_end = _dt(row.get("data_fim")) or min(self._now(), end_period)
            if row_end <= start:
                continue
            events = list(row.get("eventos") or [])
            day = max(start.date(), start_period.date())
            last_day = min(row_end.date(), end_period.date())
            while day <= last_day:
                for boundary_time in ManufacturingRules().shift_end_boundaries:
                    boundary = datetime.combine(day, boundary_time)
                    if not (start <= boundary < row_end and start_period <= boundary <= end_period):
                        continue
                    found = any(
                        str(event.get("tipo_interrupcao") or "") == "fim_turno"
                        and _dt(event.get("data_hora")) == boundary
                        for event in events
                    )
                    if not found:
                        issues.append({
                            "type": "fim_turno_sem_interrupcao_programada",
                            "severity": IssueSeverity.CRITICAL.value,
                            "message": "OP atravessou limite oficial de turno sem interrupção programada automática.",
                            "appointment_id": row.get("id"),
                            "op": row.get("op"),
                            "operation": row.get("numero_operacao"),
                            "resource": row.get("maquina"),
                            "sector": row.get("tipo_setor"),
                            "start": boundary,
                            "end": boundary,
                            "seconds": 0.0,
                            "source": "regra_manufatura",
                        })
                day += timedelta(days=1)
        return issues

    def inspect_rateio(self, sessions):
        issues = []
        for raw in sessions or ():
            row = dict(raw)
            physical = float(row.get("segundos_fisicos_periodo") or 0)
            attributed = sum(
                float(item.get("segundos_atribuidos_periodo") or 0)
                for item in (row.get("rateios") or [])
            )
            if abs(physical - attributed) > 0.05:
                issues.append({
                    "type": "rateio_nao_conserva_tempo_fisico",
                    "severity": IssueSeverity.CRITICAL.value,
                    "message": "A soma dos tempos atribuídos às OPs não conserva o tempo físico da sessão.",
                    "appointment_id": None,
                    "op": None,
                    "operation": None,
                    "resource": row.get("recurso"),
                    "sector": row.get("tipo_setor"),
                    "start": row.get("inicio_periodo") or row.get("data_inicio"),
                    "end": row.get("fim_periodo") or row.get("data_fim"),
                    "seconds": physical,
                    "physical_seconds": physical,
                    "attributed_seconds": attributed,
                    "source": "rateio",
                })
        return issues

    def inspect_calendar_gaps(self, states, *, inicio, fim, resources):
        """Lacunas entre tempo disponível de turno e estado físico registrado.

        Diagnóstico interno, **não** alerta ao usuário. Um recurso ocioso dentro
        do turno — sem OP alocada, sem operador no posto — legitimamente não
        possui estado físico, e isso não é inconsistência de dado: é a condição
        operacional "Sem apontamento", já classificada como parada não planejada
        e já visível no Andon e no OEE. Emitir a mesma informação como erro de
        auditoria produzia um alerta por recurso ocioso por dia, sem ação
        possível. O cálculo permanece aqui porque a lacuna é útil para conferir
        cobertura de calendário versus estado físico.
        """

        if self.db is None:
            return []
        calendar = CalendarService(self.db)
        issues = []
        state_rows = [dict(row) for row in (states or ())]
        states_by_resource = {}
        for row in state_rows:
            key = str(row.get("recurso") or "").strip().casefold()
            if key:
                states_by_resource.setdefault(key, []).append(row)
        for resource in resources or ():
            code = str(resource.get("codigo") or resource.get("recurso") or "").strip()
            if not code or not resource.get("calendario_codigo"):
                continue
            summary = calendar.period_summary(code, inicio, fim)
            if summary.get("availability") != "disponivel":
                continue
            covered = []
            for row in states_by_resource.get(code.casefold(), ()):
                start = _dt(row.get("inicio_periodo") or row.get("data_inicio"))
                end = _dt(row.get("fim_periodo") or row.get("data_fim")) or fim
                if start and end > start:
                    covered.append((max(start, inicio), min(end, fim)))
            covered = _merge_intervals(covered)
            for available_start, available_end in summary.get("segmentos_disponiveis") or []:
                gaps = _subtract_many([(available_start, available_end)], covered)
                for gap_start, gap_end in gaps:
                    seconds = (gap_end - gap_start).total_seconds()
                    if seconds <= 0:
                        continue
                    issues.append({
                        "type": "recurso_em_turno_sem_status",
                        "severity": IssueSeverity.INFO.value,
                        "message": (
                            "Tempo disponível de turno sem estado físico registrado "
                            "(recurso ocioso; não é inconsistência de dado)."
                        ),
                        "appointment_id": None,
                        "op": None,
                        "operation": None,
                        "resource": code,
                        "sector": resource.get("tipo_setor"),
                        "start": gap_start,
                        "end": gap_end,
                        "seconds": seconds,
                        "source": "calendario_x_estado_recurso",
                    })
        return issues

    def run_period(self, filters):
        if self.db is None:
            raise RuntimeError("AuditService.run_period exige repository/db.")
        facts_loader = getattr(self.db, "listar_fatos_operacionais_periodo", None)
        states_loader = getattr(self.db, "listar_estados_recurso_periodo", None)
        rateio_loader = getattr(self.db, "listar_rateios_tempo_periodo", None)
        resource_loader = getattr(self.db, "listar_configuracao_capacidade_recursos", None)

        facts = list(facts_loader(
            filters.inicio, filters.fim,
            setor=filters.setor, recurso=filters.recurso, op=filters.op,
            operacao=filters.operacao, produto=filters.produto,
            operador=filters.operador,
        ) or []) if callable(facts_loader) else []
        states = list(states_loader(
            filters.inicio, filters.fim,
            setor=filters.setor, recurso=filters.recurso,
            op=filters.op, operacao=filters.operacao,
        ) or []) if callable(states_loader) else []
        rateios = list(rateio_loader(
            filters.inicio, filters.fim,
            setor=filters.setor, recurso=filters.recurso,
            op=filters.op, operacao=filters.operacao,
        ) or []) if callable(rateio_loader) else []
        resources = list(resource_loader(
            setor=filters.setor, recurso=filters.recurso,
        ) or []) if callable(resource_loader) else []

        issues = self.inspect_operational_rows(facts)
        if states:
            issues.extend(self.inspect_resource_states(states, facts))
        else:
            issues.extend(self.inspect_timeline_conflicts(
                facts, inicio=filters.inicio, fim=filters.fim
            ))
        issues.extend(self.inspect_shift_boundaries(
            facts, inicio=filters.inicio, fim=filters.fim
        ))
        if rateios and not filters.op and filters.operacao is None:
            issues.extend(self.inspect_rateio(rateios))
        # Lacuna de calendário permanece calculada, mas como diagnóstico: ela
        # descreve recurso ocioso, não inconsistência de dado, e por isso não
        # entra na lista de alertas apresentada à Gestão.
        calendar_gaps = (
            self.inspect_calendar_gaps(
                states,
                inicio=filters.inicio,
                fim=filters.fim,
                resources=resources,
            )
            if states and resources
            else []
        )

        severity = {level.value: 0 for level in IssueSeverity}
        for issue in issues:
            severity[issue["severity"]] = severity.get(issue["severity"], 0) + 1
        return {
            "periodo": filters.to_dict(),
            "issues": issues,
            "count": len(issues),
            "by_severity": severity,
            "diagnostics": {
                "calendar_gaps": calendar_gaps,
                "calendar_gap_count": len(calendar_gaps),
                "calendar_gap_seconds": sum(
                    float(item.get("seconds") or 0.0) for item in calendar_gaps
                ),
                "presented_as_alert": False,
                "reason": (
                    "Recurso ocioso dentro do turno não possui estado físico e isso não "
                    "é inconsistência: é a condição 'Sem apontamento', já classificada "
                    "como parada não planejada nas métricas."
                ),
            },
            "physical_state_source": (
                "eventos_estado_recurso" if states else "timeline_apontamentos_fallback"
            ),
            "records_analyzed": len(facts),
            "resource_states_analyzed": len(states),
            "rateio_sessions_analyzed": len(rateios),
            "reliability_percentage": None,
            "reliability_reason": "Percentual de confiabilidade não será inventado sem fórmula oficial.",
        }

    def data_quality_summary(self, rows):
        """Resumo compatível com chamadas antigas, sem inventar percentual."""

        materialized = [dict(row) for row in (rows or ())]
        issues = self.inspect_operational_rows(materialized)
        issues.extend(self.inspect_timeline_conflicts(materialized))
        severity = {level.value: 0 for level in IssueSeverity}
        affected = set()
        for issue in issues:
            severity[issue["severity"]] = severity.get(issue["severity"], 0) + 1
            if issue.get("appointment_id") is not None:
                affected.add(issue["appointment_id"])
        timeline_conflicts = sum(
            1 for issue in issues
            if issue.get("type") in {
                "sobreposicao_estados_incompativeis",
                "recurso_em_setores_conflitantes",
            }
        )
        return {
            "records_analyzed": len(materialized),
            "records_with_issue": len(affected),
            "issues": len(issues),
            "timeline_conflicts": timeline_conflicts,
            "by_severity": severity,
            "reliability_percentage": None,
            "reliability_reason": "Percentual de confiabilidade permanece indefinido até existir fórmula oficial.",
        }

    @staticmethod
    def _issue(kind, severity, message, row):
        return {
            "type": kind,
            "severity": severity.value,
            "message": message,
            "appointment_id": row.get("id"),
            "op": row.get("op"),
            "operation": row.get("numero_operacao"),
            "resource": row.get("maquina"),
            "sector": row.get("tipo_setor"),
        }


def _dt(value):
    if value is None or isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def _overlaps(start_a, end_a, start_b, end_b):
    return bool(start_b and end_b and start_a < end_b and end_a > start_b)


def _subtract_many(intervals, cuts):
    result = list(intervals)
    for cut_start, cut_end in cuts:
        next_result = []
        for start, end in result:
            if cut_end <= start or cut_start >= end:
                next_result.append((start, end))
                continue
            if cut_start > start:
                next_result.append((start, min(cut_start, end)))
            if cut_end < end:
                next_result.append((max(cut_end, start), end))
        result = [(start, end) for start, end in next_result if end > start]
    return result


def _merge_intervals(intervals):
    ordered = sorted(
        ((start, end) for start, end in intervals if end > start),
        key=lambda item: (item[0], item[1]),
    )
    if not ordered:
        return []
    merged = [ordered[0]]
    for start, end in ordered[1:]:
        previous_start, previous_end = merged[-1]
        if start <= previous_end:
            merged[-1] = (previous_start, max(previous_end, end))
        else:
            merged.append((start, end))
    return merged
