"""Façade estável para o frontend atual e para a futura API Web.

A interface não deve consultar tabelas nem recalcular indicadores. Cada tela
consome contratos desta camada, garantindo uma única verdade funcional na Web.
"""

from __future__ import annotations

from datetime import datetime

from app.core.resource_mapping import resource_display_name
from app.database.schema import SCHEMA_VERSION
from mes.analytics.resource_state import classify_state_row
from mes.contracts import (
    AnalyticsFilter,
    FRONTEND_CONTRACT_VERSION,
    MANAGEMENT_SECTIONS,
    ReportError,
)
from mes.domain import (
    ManufacturingRules,
    NO_APPOINTMENT_STOP_REASON,
    PLANNED_STOP_GROUP_CODES,
    RESOURCE_WITHOUT_OP_STOP_REASON,
    STOP_CLASSIFICATION_COLORS,
    STOP_CLASSIFICATION_UI_TOKENS,
)
from mes.services.audit import AuditService
from mes.services.andon import AndonService
from mes.services.calendar import CalendarService
from mes.services.industrial_analytics import IndustrialAnalyticsService
from mes.services.management import ManagementService
from mes.services.management_insights import ManagementInsightsService
from mes.services.traceability import TraceabilityService
from mes.services.welding import WeldingManagementService


#: Tipos aceitos pela fachada de relatórios da Web. A lista é o contrato: um
#: tipo fora dela é erro do cliente (4xx), não falha do servidor.
FACADE_REPORT_TYPES = (
    "gerencial",
    "producao",
    "perdas",
    "indicadores",
    "dados_analiticos",
)


class FrontendBackendFacade:
    """Agrupa casos de uso por seção visual, sem depender do adaptador HTTP."""

    def __init__(self, db, now_func=None, simulation_mode=False):
        self.db = db
        self._now = now_func or datetime.now
        self.simulation_mode = bool(simulation_mode)
        self.management = ManagementService(
            db,
            now_func=self._now,
            simulation_mode=self.simulation_mode,
        )
        self.analytics = IndustrialAnalyticsService(
            db,
            now_func=self._now,
            simulation_mode=self.simulation_mode,
            management=self.management,
        )
        self.management_insights = ManagementInsightsService(
            db,
            management=self.management,
            analytics=self.analytics,
            now_func=self._now,
            simulation_mode=self.simulation_mode,
        )
        self.audit_service = AuditService(db, now_func=self._now)
        self.traceability = TraceabilityService(db)
        self.andon_service = AndonService(
            db,
            simulation_mode=self.simulation_mode,
        )
        self.welding_management = WeldingManagementService(
            db,
            now_func=self._now,
            simulation_mode=self.simulation_mode,
        )

    def capabilities(self):
        """Expõe o contrato que a UI deve obedecer sem duplicar regra de negócio."""

        rules = ManufacturingRules()
        return {
            "contract_version": FRONTEND_CONTRACT_VERSION,
            "schema_version": SCHEMA_VERSION,
            "sections": list(MANAGEMENT_SECTIONS),
            "calculation_policy": "backend_only",
            "canonical_sources": {
                "physical_resource_state": "eventos_estado_recurso",
                "production_quantities": "eventos_quantidade_producao",
                "op_execution": "apontamentos_operacionais+eventos_apontamento_operador",
                "allocated_op_time": "sessoes_recurso+rateios_tempo_op",
                "calendar": "calendarios_produtivos+turnos_produtivos+intervalos_turno_produtivo+excecoes_calendario_produtivo",
                "cut_nesting": "apontamentos_corte",
            },
            "manufacturing_rules": {
                "produced_quantity": "good_only",
                "shift_end_boundaries": [value.strftime("%H:%M") for value in rules.shift_end_boundaries],
                "official_work_window": [
                    value.strftime("%H:%M") for value in rules.official_work_window
                ],
                "overtime_windows": [
                    [value.strftime("%H:%M") for value in window]
                    for window in rules.overtime_windows
                ],
                "automatic_breaks": [
                    {
                        "start": start.strftime("%H:%M"),
                        "end": end.strftime("%H:%M"),
                        "name": name,
                    }
                    for start, end, name in rules.automatic_breaks
                ],
                "shift_end_action": "automatic_planned_interruption_without_quantity_op_remains_open",
                "setup_is_productive": rules.is_productive("setup"),
                "setup_affects_availability": False,
                "setup_affects_performance": False,
                "manual_stop_is_planned": rules.manual_stop_is_planned(),
                "automatic_stop_is_planned": rules.automatic_stop_is_planned(),
                "simultaneous_ops_duplicate_physical_time": False,
                # Calendário operacional (Wave 6A)
                "out_of_shift_window": ["17:30", "08:00"],
                "planned_overtime_source": "excecoes_calendario_produtivo:disponivel_extra",
                "planned_overtime_is_fixed_second_shift": False,
                "clock_blocks_appointment": False,
                "out_of_shift_counts_as_availability": False,
                "out_of_shift_is_machine_downtime": False,
                "out_of_shift_is_global_calendar_quantity": True,
                "planned_stop_groups": list(PLANNED_STOP_GROUP_CODES),
                "planned_stop_affects_oee": False,
                "unplanned_stop_affects_oee": True,
                "stop_classification_colors": {
                    classification.value: color
                    for classification, color in STOP_CLASSIFICATION_COLORS.items()
                },
                "stop_classification_ui_tokens": {
                    classification.value: token
                    for classification, token in STOP_CLASSIFICATION_UI_TOKENS.items()
                },
                "always_unplanned_conditions": [
                    NO_APPOINTMENT_STOP_REASON,
                    RESOURCE_WITHOUT_OP_STOP_REASON,
                ],
            },
            "ui_policy": {
                "management_correction_or_edit_tab": False,
                "frontend_must_recalculate_metrics": False,
                "frontend_must_infer_missing_data": False,
            },
            "pending_official_definition": {
                "oee_ftt_with_scrap_rework": False,
                "corporate_database_mapping": True,
                "rateio_strategy_by_scenario": True,
            },
        }

    def inicio(self, filters: AnalyticsFilter, *, include_insights=True):
        payload = self.management.get_overview(filters)
        payload["sector_highlights"] = self._sector_highlights(
            payload.get("sectors", [])
        )
        hours = payload.get("hours", {})
        composition = (
            ("Produção", "production_seconds"),
            ("Setup", "setup_seconds"),
            ("Paradas", "downtime_seconds"),
            ("Retrabalho", "rework_seconds"),
            ("Atividade sem OP", "activity_without_op_seconds"),
            ("Fila / espera", "queue_seconds"),
            ("Fora do turno", "out_of_shift_seconds"),
        )
        items = [
            {"label": label, "seconds": float(hours.get(field) or 0.0), "source_field": field}
            for label, field in composition
        ]
        total = sum(item["seconds"] for item in items)
        for item in items:
            item["percentage"] = item["seconds"] / total * 100.0 if total > 0 else None
        payload["time_composition"] = {
            "items": items,
            "total_seconds": total,
            "availability": "disponivel" if total > 0 else "sem_registros",
        }
        simulation = payload.get("simulation") or {}
        if self.simulation_mode and simulation:
            payload["production_plan"] = {
                "value": simulation.get("planned_quantity"),
                "availability": "disponivel",
                "unit": " peças",
                "reason": "Planejamento sintético exclusivo do modo de simulação histórica.",
            }
        else:
            payload["production_plan"] = {
                "value": None,
                "availability": "dados_insuficientes",
                "reason": (
                    "O total planejado depende do contrato corporativo Protheus/TOTVS e não será "
                    "inferido a partir de apontamentos por operação."
                ),
            }
        if include_insights:
            payload["insights"] = self.management_insights.build(filters, overview=payload)
        return payload

    @staticmethod
    def _sector_highlights(sectors):
        """Seleciona extremos gerenciais sem recalcular grandezas industriais."""

        rows = [dict(row) for row in (sectors or ())]
        if not rows:
            return []
        definitions = (
            ("maior_producao_boa", "Maior produção boa", "producao_boa", max, "peças"),
            ("maior_refugo", "Maior refugo", "refugo", max, "peças"),
            ("menor_tempo_producao", "Menor tempo de produção", "tempo_producao_segundos", min, "s"),
            ("maior_tempo_parada", "Maior tempo de parada", "tempo_parada_segundos", max, "s"),
        )
        highlights = []
        for key, label, field, chooser, unit in definitions:
            candidates = [
                row for row in rows
                if row.get(field) is not None
                and (
                    field != "tempo_producao_segundos"
                    or int(row.get("ops") or 0) > 0
                    or float(row.get(field) or 0) > 0
                )
            ]
            if not candidates:
                continue
            selected = chooser(
                candidates,
                key=lambda row: (
                    float(row.get(field) or 0),
                    str(row.get("setor") or "").casefold(),
                ),
            )
            highlights.append({
                "key": key,
                "label": label,
                "sector": selected.get("setor"),
                "value": float(selected.get(field) or 0),
                "unit": unit,
            })
        return highlights

    def insights(self, filters: AnalyticsFilter):
        overview = self.management.get_overview(filters)
        return self.management_insights.build(filters, overview=overview)

    def explain_kpi(self, key: str, filters: AnalyticsFilter):
        overview = self.management.get_overview(filters)
        return self.management_insights.explain_kpi(key, filters, overview=overview)

    def consulta_operacional(self, filters: AnalyticsFilter, *, somente_vinculo_operacional=False):
        now = min(self._now(), filters.fim)
        # Instanciado uma vez por consulta: o serviço já memoiza turnos e
        # exceções por recurso, então a classificação de janela não multiplica
        # consulta por card do Andon.
        calendar = CalendarService(self.db)
        states_loader = getattr(self.db, "listar_estados_recurso_atuais", None)
        states = list(states_loader(
            setor=filters.setor,
            recurso=filters.recurso,
            reference_time=now,
        ) or []) if callable(states_loader) else []

        facts_loader = getattr(self.db, "listar_fatos_operacionais_periodo", None)
        facts = list(facts_loader(
            filters.inicio,
            filters.fim,
            setor=filters.setor,
            recurso=filters.recurso,
            op=filters.op,
            operacao=filters.operacao,
            produto=filters.produto,
            operador=filters.operador,
        ) or []) if callable(facts_loader) else []

        active_by_resource = {}
        for fact in facts:
            if fact.get("status") not in {"Em processo", "Parada", "Setup", "Retrabalho"}:
                continue
            resource = str(fact.get("maquina") or "").strip()
            if not resource:
                continue
            active_by_resource.setdefault(resource.casefold(), []).append({
                "apontamento_id": fact.get("id"),
                "recurso": resource,
                "setor": fact.get("tipo_setor"),
                "op": fact.get("op"),
                "operacao": fact.get("numero_operacao"),
                "descricao_operacao": fact.get("descricao_operacao"),
                "produto": fact.get("produto_codigo") or fact.get("peca"),
                "descricao_produto": fact.get("produto_descricao") or fact.get("descricao_produto"),
                "quantidade_planejada": (
                    fact.get("quantidade_planejada_pcp")
                    if fact.get("quantidade_planejada_pcp") is not None
                    else fact.get("quantidade")
                ),
                "quantidade_boa": fact.get("quantidade_boa"),
                "refugo": fact.get("quantidade_refugo"),
                "retrabalho": fact.get("quantidade_retrabalho"),
                "operador_inicio": fact.get("operador_inicio"),
                "status": fact.get("status"),
                "inicio": fact.get("data_inicio"),
            })

        items = []
        for state in states:
            resource = str(state.get("recurso") or "").strip()
            start = state.get("data_inicio")
            elapsed = None
            if isinstance(start, datetime):
                elapsed = max(0.0, (now - start).total_seconds())
            # Classificação e cor decididas uma única vez, no domínio.
            classification = classify_state_row(state)
            ops_ativas = active_by_resource.get(resource.casefold(), [])
            items.append({
                # Fora de turno, sem HE e sem ninguém trabalhando: ausência de
                # demanda, não parada. Quem decide é o domínio; o calendário do
                # próprio recurso diz se o instante é operacional. O instante
                # certo é quando o ESTADO começou (``start``), não o limite do
                # filtro (``now`` pode ser o fim de uma janela histórica, ex.:
                # 23:59:59 de um dia consultado) — senão um recurso em fila às
                # 14h30, dentro do turno, seria classificado pelo fim do dia.
                "sem_demanda": ManufacturingRules.resource_has_no_demand(
                    category=state.get("categoria"),
                    window_kind=calendar.shift_window_kind(
                        resource, start if isinstance(start, datetime) else now
                    ),
                    active_operations=len(ops_ativas),
                ),
                # A visão de posto só publica execução registrada. Uma OP,
                # rota, demanda ou elegibilidade não substitui apontamento.
                # Evento físico manual e apontamento operacional ativo são as
                # duas fontes canônicas desta projeção.
                "tem_apontamento_canonico": bool(ops_ativas) or not bool(state.get("automatico")),
                "estado_recurso_id": state.get("id"),
                "recurso": resource,
                "setor": state.get("tipo_setor"),
                "categoria": state.get("categoria"),
                "classificacao_parada": (
                    classification.value if classification is not None else None
                ),
                "cor_parada": (
                    ManufacturingRules.stop_classification_ui_token(classification)
                    if classification is not None
                    else None
                ),
                "codigo_status": state.get("codigo_status_recurso"),
                "motivo": state.get("motivo"),
                "comentario": state.get("comentario"),
                "tipo_atividade": state.get("tipo_atividade"),
                "descricao_atividade": state.get("descricao_atividade"),
                "causa_raiz": state.get("causa_raiz"),
                "inicio": start,
                "duracao_segundos": elapsed,
                "planejado": state.get("planejado"),
                "automatico": bool(state.get("automatico")),
                "tipo_interrupcao": state.get("tipo_interrupcao"),
                "op_estado": state.get("op"),
                "operacao_estado": state.get("numero_operacao"),
                "produto_estado": state.get("produto_codigo"),
                "operador_estado": state.get("operador"),
                "ops_ativas": ops_ativas,
                "quantidade_ops_ativas": len(ops_ativas),
                "fonte": "eventos_estado_recurso",
            })

        # Se o banco ainda não tem estado canônico histórico/atual, expõe os
        # fatos sem fabricar um estado físico agregado.
        if not states:
            for resource_key, operations in sorted(active_by_resource.items()):
                resource = operations[0].get("recurso") if operations else resource_key
                sector = operations[0].get("setor") if operations else None
                items.append({
                    "estado_recurso_id": None,
                    "recurso": resource,
                    "setor": sector,
                    "categoria": "desconhecido",
                    "codigo_status": None,
                    "motivo": "Estado físico canônico ainda não registrado para este recurso.",
                    "causa_raiz": None,
                    "inicio": None,
                    "duracao_segundos": None,
                    "planejado": None,
                    "automatico": False,
                    "tipo_interrupcao": None,
                    "ops_ativas": operations,
                    "quantidade_ops_ativas": len(operations),
                    "tem_apontamento_canonico": True,
                    "fonte": "fatos_operacionais_sem_estado_fisico",
                })

        items.sort(key=lambda row: (
            str(row.get("setor") or "").casefold(),
            str(row.get("recurso") or "").casefold(),
        ))
        result = {
            "periodo": filters.to_dict(),
            "agora": now,
            "resources": items,
            "count": len(items),
        }
        if self.simulation_mode:
            configured_loader = getattr(self.db, "listar_configuracao_capacidade_recursos", None)
            configured = list(configured_loader(setor=filters.setor, recurso=filters.recurso) or []) if callable(configured_loader) else []
            present = {str(item.get("recurso") or "").strip().casefold() for item in items}
            queued_by_resource = {}
            for fact in facts:
                if str(fact.get("status") or "") != "Aguardando":
                    continue
                resource = str(fact.get("maquina") or "").strip()
                if resource:
                    queued_by_resource.setdefault(resource.casefold(), []).append({
                        "apontamento_id": fact.get("id"),
                        "recurso": resource,
                        "setor": fact.get("tipo_setor"),
                        "op": fact.get("op"),
                        "operacao": fact.get("numero_operacao"),
                        "descricao_operacao": fact.get("descricao_operacao"),
                        "produto": fact.get("produto_codigo") or fact.get("peca"),
                        "descricao_produto": fact.get("produto_descricao") or fact.get("descricao_produto"),
                        "quantidade_planejada": (
                            fact.get("quantidade_planejada_pcp")
                            if fact.get("quantidade_planejada_pcp") is not None
                            else fact.get("quantidade")
                        ),
                        "quantidade_boa": fact.get("quantidade_boa"),
                        "refugo": fact.get("quantidade_refugo"),
                        "retrabalho": fact.get("quantidade_retrabalho"),
                        "operador_inicio": fact.get("operador_inicio"),
                        "status": fact.get("status"),
                        "inicio": fact.get("data_entrada"),
                    })
            for resource in configured:
                code = str(resource.get("codigo") or resource.get("nome") or "").strip()
                if not code:
                    continue
                # O estado físico é gravado com o nome do posto (`Gasparini`),
                # enquanto o catálogo guarda o código técnico (`DOBRA1`). Sem
                # resolver a identidade pelo mapa canônico, a mesma máquina
                # apareceria duas vezes no mesmo instante: uma com o estado
                # real e outra como "livre".
                identities = {
                    code.casefold(),
                    resource_display_name(code, resource.get("nome")).casefold(),
                }
                identities.discard("")
                if identities & present:
                    continue
                queued = next(
                    (
                        queued_by_resource[identity]
                        for identity in sorted(identities)
                        if identity in queued_by_resource
                    ),
                    [],
                )
                items.append({
                    "estado_recurso_id": None,
                    "recurso": code,
                    "setor": resource.get("tipo_setor"),
                    "categoria": "aguardando" if queued else "livre",
                    "codigo_status": None,
                    "motivo": "OP aguardando liberação" if queued else "Recurso livre no instante simulado.",
                    "causa_raiz": None,
                    "inicio": queued[0].get("inicio") if queued else None,
                    "duracao_segundos": None,
                    "planejado": bool(queued),
                    "automatico": False,
                    "tipo_interrupcao": None,
                    "op_estado": None,
                    "operacao_estado": None,
                    "produto_estado": None,
                    "operador_estado": None,
                    "ops_ativas": queued,
                    "quantidade_ops_ativas": len(queued),
                    "tem_apontamento_canonico": bool(queued),
                    "fonte": "catalogo_recursos_pcfactory+apontamentos_operacionais",
                })
            items.sort(key=lambda row: (
                str(row.get("setor") or "").casefold(),
                str(row.get("recurso") or "").casefold(),
            ))
            result["count"] = len(items)
            result["simulation_reference_time"] = self._now()
        # Corte possui apontamento próprio, fora de
        # ``apontamentos_operacionais``. Ele é execução canônica e portanto
        # deve projetar Laser/Plasma mesmo se o último evento físico visível
        # for o fechamento automático de turno.
        cut_loader = getattr(self.db, "listar_cortes_ativos_andon", None)
        for raw_cut in (cut_loader() or []) if callable(cut_loader) else []:
            cut = dict(raw_cut or {})
            resource = str(cut.get("maquina") or "").strip()
            if not resource:
                continue
            item = next((row for row in items if str(row.get("recurso") or "").strip().casefold() == resource.casefold()), None)
            if item is None:
                item = {"recurso": resource, "setor": "Corte"}
                items.append(item)
            item.update({
                "estado_recurso_id": item.get("estado_recurso_id"),
                "categoria": "producao",
                "inicio": cut.get("data_inicio"),
                "duracao_segundos": max(0.0, (now - cut["data_inicio"]).total_seconds()) if isinstance(cut.get("data_inicio"), datetime) else None,
                "op_estado": None,
                "operacao_estado": None,
                "produto_estado": None,
                "operador_estado": cut.get("operador_inicio"),
                "ops_ativas": [],
                "quantidade_ops_ativas": 0,
                "tem_apontamento_canonico": True,
                "fonte": "apontamentos_corte",
                "codigo_tarefa_corte": cut.get("codigo_tarefa"),
                "programa_corte": cut.get("programa"),
                "chapa_corte": cut.get("nome_chapa"),
                "repeticao_corte": cut.get("repeticao"),
            })
        items.sort(key=lambda row: (
            str(row.get("setor") or "").casefold(),
            str(row.get("recurso") or "").casefold(),
        ))
        result["resources"] = items
        result["count"] = len(items)
        if somente_vinculo_operacional:
            # Uso exclusivo de visões por posto, como o Dev Observatory.
            # Inventário, elegibilidade, rota e demanda não são apontamento.
            result["resources"] = [
                item for item in result["resources"]
                if item.get("tem_apontamento_canonico")
            ]
            result["count"] = len(result["resources"])
        return result

    def andon(self, filters: AnalyticsFilter):
        """Entrega um snapshot fabril único sem mover cálculos para a Web."""

        operational = self.consulta_operacional(filters)
        # O Andon usa apenas o resumo consolidado. Não carregar o dashboard de
        # exceções aqui preserva a projeção única da TV e evita consultas extras.
        overview = self.inicio(filters, include_insights=False)
        return self.andon_service.build_snapshot(
            filters,
            operational=operational,
            overview=overview,
        )

    def solda_gerencial(self):
        """Acompanhamento gerencial da Solda, sem recorte de período.

        A PCP acompanha a situação corrente das OPs de conjunto soldado, não um
        intervalo fechado; por isso a visão não recebe filtro de período e a
        mesma projeção serve a tela de gestão e o ciclo da TV.
        """

        return self.welding_management.acompanhamento()

    def producao(self, filters: AnalyticsFilter):
        return {
            "periodo": filters.to_dict(),
            "planejado_x_realizado": self.analytics.planned_vs_actual(filters),
            "tempo_padrao_x_real": self.analytics.standard_vs_actual(filters),
            "nestings": self.management.get_nesting_times(filters),
        }

    def ordens_producao(self, filters: AnalyticsFilter):
        """Projeção de OPs para a Web sem deslocar regra para o React."""

        loader = getattr(self.db, "listar_fatos_operacionais_periodo", None)
        facts = list(loader(
            filters.inicio,
            filters.fim,
            setor=filters.setor,
            recurso=filters.recurso,
            op=filters.op,
            operacao=filters.operacao,
            produto=filters.produto,
            operador=filters.operador,
        ) or []) if callable(loader) else []

        items = []
        for fact in facts:
            planned = (
                fact.get("quantidade_planejada_pcp")
                if fact.get("quantidade_planejada_pcp") is not None
                else fact.get("quantidade")
            )
            good = int(fact.get("quantidade_boa") or 0)
            scrap = int(fact.get("quantidade_refugo") or 0)
            attended = ManufacturingRules.attended_quantity(good, scrap)
            balance = (
                ManufacturingRules.quantity_remaining(planned, good, scrap)
                if planned is not None
                else None
            )
            progress = None
            if planned is not None and int(planned) > 0:
                progress = min(100.0, max(0.0, attended / int(planned) * 100.0))
            items.append({
                "apontamento_id": fact.get("id"),
                "op": fact.get("op"),
                "produto": fact.get("produto_codigo") or fact.get("peca"),
                "descricao": fact.get("produto_descricao") or fact.get("descricao_produto"),
                "operacao_atual": fact.get("numero_operacao"),
                "descricao_operacao": fact.get("descricao_operacao"),
                "sequencia": fact.get("sequencia_operacao"),
                "setor": fact.get("tipo_setor"),
                "recurso_planejado": fact.get("codigo_recurso"),
                "recurso_real": fact.get("maquina"),
                "prioridade": fact.get("prioridade"),
                "inicio_planejado": fact.get("inicio_planejado"),
                "fim_planejado": fact.get("fim_planejado"),
                "prazo_entrega": fact.get("prazo_entrega"),
                "inicio_real": fact.get("data_inicio"),
                "fim_real": fact.get("data_fim"),
                # A Auditoria precisa responder "quem", e o operador que
                # iniciou a execução já vem no fato canônico.
                "operador_inicio": fact.get("operador_inicio"),
                "operador_fim": fact.get("operador_fim"),
                "quantidade_planejada": planned,
                "quantidade_boa": good,
                "refugo": scrap,
                "retrabalho": int(fact.get("quantidade_retrabalho") or 0),
                "quantidade_atendida": attended,
                "saldo_quantidade": balance,
                "progresso_percentual": progress,
                "status": fact.get("status"),
                "proxima_operacao": fact.get("proxima_operacao"),
                "fonte": "apontamentos_operacionais+eventos_apontamento_operador",
            })
        return {
            "periodo": filters.to_dict(),
            "items": items,
            "count": len(items),
            "availability": "disponivel" if items else "sem_registros",
        }

    def producao_realizada(self, filters: AnalyticsFilter):
        overview = self.management.get_overview(filters)
        return {
            "periodo": filters.to_dict(),
            "production": overview.get("production", {}),
            "sectors": overview.get("sectors", []),
            "quality": self.analytics.quality(filters),
        }

    def nestings(self, filters: AnalyticsFilter):
        items = self.management.get_nesting_times(filters)
        return {
            "periodo": filters.to_dict(),
            "items": items,
            "count": len(items),
            "availability": "disponivel" if items else "sem_registros",
            "time_policy": {
                "total_field": "real_segundos",
                "filtered_period_field": "real_periodo_segundos",
                "reason": (
                    "O tempo total do nesting permanece distinto do tempo do nesting "
                    "dentro do período filtrado."
                ),
            },
        }

    def relatorio(self, report_type: str, filters: AnalyticsFilter):
        """Compõe relatórios a partir dos mesmos casos de uso gerenciais."""

        key = str(report_type or "").strip().casefold()
        if key == "gerencial":
            return {"type": key, "overview": self.inicio(filters)}
        if key == "producao":
            return {"type": key, **self.producao_realizada(filters)}
        if key == "perdas":
            return {
                "type": key,
                "periodo": filters.to_dict(),
                "paradas": self.analise("paradas", filters),
                "qualidade": self.analise("qualidade", filters),
            }
        if key == "indicadores":
            return {
                "type": key,
                "periodo": filters.to_dict(),
                "analytics": {
                    "tempos": self.analise("tempos", filters),
                    "qualidade": self.analise("qualidade", filters),
                    "capacidade": self.analise("capacidade", filters),
                    "confiabilidade": self.analise("confiabilidade", filters),
                    "oee": self.analise("oee", filters),
                },
            }
        if key == "dados_analiticos":
            return {
                "type": key,
                "periodo": filters.to_dict(),
                "orders": self.ordens_producao(filters),
                "audit": self.auditoria(filters),
                "nestings": self.nestings(filters),
            }
        raise ReportError(
            "report_type_invalido",
            (
                "Tipo de relatório inválido. Use um de: "
                + ", ".join(FACADE_REPORT_TYPES)
                + "."
            ),
            status_code=400,
        )

    def analises(self, filters: AnalyticsFilter):
        tempos = self.analise("tempos", filters)
        qualidade = self.analise("qualidade", filters)
        oee = self.analise("oee", filters)
        return {
            "periodo": filters.to_dict(),
            "tempos": tempos,
            "paradas": self.analise("paradas", filters),
            "setup": self.analise("setup", filters),
            "qualidade": qualidade,
            "tempo_padrao_x_real": self.analise("tempo_padrao_x_real", filters),
            "cronoanalise": self.analise("cronoanalise", filters),
            "capacidade": self.analise("capacidade", filters),
            "confiabilidade": self.analise("confiabilidade", filters),
            "oee": oee,
        }

    def analise(self, key: str, filters: AnalyticsFilter):
        """Executa apenas a análise solicitada pela rota Web."""

        if key == "tempos":
            payload = self.analytics.time_breakdown(filters)
            if self.simulation_mode:
                payload["simulation"] = self.management.get_overview(filters).get("simulation")
            return payload
        if key == "paradas":
            return self.analytics.downtimes(filters)
        if key == "setup":
            return self.analytics.setups(filters)
        if key == "qualidade":
            return self.analytics.quality(filters)
        if key == "tempo_padrao_x_real":
            return self.analytics.standard_vs_actual(filters)
        if key == "cronoanalise":
            return self.analytics.chronoanalysis(filters)
        if key == "capacidade":
            return self.analytics.capacity_configuration(filters)
        if key == "confiabilidade":
            return self.analytics.reliability(filters)
        if key == "oee":
            # Resumo e série compartilham a mesma janela lida uma única vez.
            # Sem isto, o resumo do período e cada ponto da evolução repetiriam
            # as mesmas consultas.
            bounds = self.management._bucket_bounds(filters)
            periodos = [(filters.inicio, filters.fim), *bounds]
            with self.management._janela_prefetch(filters, periodos=periodos):
                overview = self.management.get_overview(filters)
                evolution = self.management.get_oee_evolution(filters)
            return {
                **(overview.get("kpis", {}).get("oee") or {}),
                "evolution": evolution,
                "extended_metrics": overview.get("kpis_estendidos") or {},
                "losses_breakdown": overview.get("kpi_losses_breakdown") or {},
            }
        raise ValueError("Análise solicitada não existe.")

    def auditoria(self, filters: AnalyticsFilter):
        return self.audit_service.run_period(filters)

    def rastreabilidade(self, op: str):
        return self.traceability.trace_op(op)
