"""Análises industriais reutilizáveis pela API Web e por exportações.

O serviço trabalha somente com fatos disponíveis. Métricas cuja regra oficial
não está fechada continuam fora daqui ou retornam disponibilidade explícita.
"""

from collections import defaultdict
from datetime import datetime
from statistics import mean, median, pstdev

from mes.analytics.physical_time import PhysicalInputSegment, consolidate_physical_time
from mes.analytics.resource_state import build_physical_state_inputs
from mes.analytics.timeline import build_operator_timeline
from mes.contracts import AnalyticsFilter
from mes.domain import DataAvailability, EventCategory, ManufacturingRules
from mes.services.calendar import CalendarService
from mes.services.management import ManagementService
from mes.services.shift_parameters import load_manufacturing_rules


class IndustrialAnalyticsService:
    def __init__(self, db, now_func=None, simulation_mode=False, management=None):
        self.db = db
        self._now = now_func or datetime.now
        self.simulation_mode = bool(simulation_mode)
        self.rules = load_manufacturing_rules(db)
        self.management = management or ManagementService(
            db,
            now_func=self._now,
            simulation_mode=self.simulation_mode,
        )
        self._cache = {}

    def time_breakdown(self, filters: AnalyticsFilter) -> dict:
        cache_key = ("time_breakdown", filters)
        if cache_key in self._cache:
            return self._cache[cache_key]
        facts = self._facts(filters)
        state_source_available, state_rows = self._resource_states(filters)
        use_canonical_resource_state = bool(state_source_available and state_rows)
        physical_inputs = []
        if use_canonical_resource_state:
            physical_inputs = build_physical_state_inputs(
                state_rows,
                inicio=filters.inicio,
                fim=filters.fim,
            )
        else:
            for row in facts:
                timeline = self._timeline(row, filters)
                if timeline is None:
                    continue
                sector = str(row.get("tipo_setor") or "Não informado")
                resource = str(row.get("maquina") or "Não informado")
                for segment in timeline.segments:
                    physical_inputs.append(PhysicalInputSegment(
                        resource=resource,
                        sector=sector,
                        category=(segment.category if timeline.has_event_data else EventCategory.UNKNOWN),
                        start=segment.start,
                        end=segment.end,
                        source_ref=f"apontamento:{row.get('id')}",
                    ))

        nesting_rows = self._nestings(filters)
        undated_cutting_seconds = 0.0
        for row in nesting_rows:
            start = _dt(row.get("inicio"))
            end = _dt(row.get("fim")) or (min(self._now(), filters.fim) if start else None)
            if start and end:
                clip_start = max(start, filters.inicio)
                clip_end = min(end, filters.fim)
                if clip_end > clip_start:
                    if not use_canonical_resource_state:
                        physical_inputs.append(PhysicalInputSegment(
                            resource=str(row.get("maquina") or "Não informado"),
                            sector="Corte",
                            category=EventCategory.PRODUCTION,
                            start=clip_start,
                            end=clip_end,
                            source_ref=f"nesting:{row.get('apontamento_id')}",
                        ))
                    continue
            # Fontes legadas podem ter apenas a duração. Sem início/fim não há
            # como remover sobreposição com segurança, então o caso fica explícito.
            if not use_canonical_resource_state:
                undated_cutting_seconds += float(
                    row.get("real_periodo_segundos", row.get("real_segundos")) or 0
                )

        physical = consolidate_physical_time(physical_inputs)
        totals = defaultdict(float, physical["totals"])
        by_sector = defaultdict(lambda: defaultdict(float))
        by_resource = defaultdict(lambda: defaultdict(float))
        for key, value in physical["by_sector"].items():
            by_sector[key].update(value)
        for key, value in physical["by_resource"].items():
            by_resource[key].update(value)

        if undated_cutting_seconds:
            totals[EventCategory.PRODUCTION] += undated_cutting_seconds
            by_sector["Corte"][EventCategory.PRODUCTION] += undated_cutting_seconds

        payload = {
            "periodo": filters.to_dict(),
            "totals": _category_dict(totals),
            "physical_seconds": physical["physical_seconds"] + undated_cutting_seconds,
            "raw_attributed_timeline_seconds": (
                physical["raw_attributed_seconds"] + undated_cutting_seconds
            ),
            "overlap_removed_seconds": physical["overlap_removed_seconds"],
            "overlap_seconds": physical["overlap_seconds"],
            "conflicting_state_seconds": physical["conflicting_state_seconds"],
            "conflicting_sector_seconds": physical["conflicting_sector_seconds"],
            # `totals[fora_turno]` é a união temporal global do calendário, por
            # isso pode ser menor que a soma por recurso. A diferença fica
            # explícita em vez de silenciosa.
            "out_of_shift_attributed_seconds": physical["out_of_shift_attributed_seconds"],
            "out_of_shift_duplicated_seconds": physical["out_of_shift_duplicated_seconds"],
            "by_sector": [
                {"setor": key, **_category_dict(value)}
                for key, value in sorted(by_sector.items(), key=lambda item: item[0].casefold())
            ],
            "by_resource": [
                {"recurso": key, **_category_dict(value)}
                for key, value in sorted(by_resource.items(), key=lambda item: item[0].casefold())
            ],
            "cutting_nestings": nesting_rows,
            "availability": DataAvailability.PARTIAL.value,
            "physical_state_source": (
                "eventos_estado_recurso"
                if use_canonical_resource_state
                else "timeline_apontamentos_fallback"
            ),
            "physical_state_rows": len(state_rows),
            "reason": (
                "A fonte física preferencial é eventos_estado_recurso. Timelines por OP são apenas "
                "fallback histórico. OPs simultâneas nunca multiplicam o tempo real da máquina; "
                "conflitos permanecem como desconhecido."
            ),
        }
        self._cache[cache_key] = payload
        return payload

    def downtimes(self, filters: AnalyticsFilter) -> dict:
        # Intervalo automático (almoço/café) é pausa do calendário, não perda:
        # fica fora de rankings, exceções e análises de paradas. A composição
        # física do tempo continua vindo da timeline completa.
        rows = [
            row for row in self._segments(filters, EventCategory.DOWNTIME)
            if not row.get("automatica")
        ]
        return self._segment_summary(filters, rows, label="paradas")

    def setups(self, filters: AnalyticsFilter) -> dict:
        rows = self._segments(filters, EventCategory.SETUP)
        return self._segment_summary(filters, rows, label="setups")

    def quality(self, filters: AnalyticsFilter) -> dict:
        cache_key = ("quality", filters)
        if cache_key in self._cache:
            return self._cache[cache_key]
        events, complete_source = self._quantity_events(filters)
        totals = {"boa": 0, "refugo": 0, "retrabalho": 0}
        by_sector = defaultdict(lambda: {"boa": 0, "refugo": 0, "retrabalho": 0})
        by_product = defaultdict(lambda: {"boa": 0, "refugo": 0, "retrabalho": 0})
        scrap_reasons = defaultdict(int)
        rework_reasons = defaultdict(int)
        for event in events:
            kind = str(event.get("tipo") or "").strip().casefold()
            if kind not in totals:
                continue
            qty = max(0, int(event.get("quantidade") or 0))
            totals[kind] += qty
            sector = str(event.get("tipo_setor") or "Não informado")
            product = str(event.get("produto_codigo") or "Não informado")
            by_sector[sector][kind] += qty
            by_product[product][kind] += qty
            reason = str(event.get("motivo") or "Não informado")
            if kind == "refugo":
                scrap_reasons[reason] += qty
            elif kind == "retrabalho":
                rework_reasons[reason] += qty

        # O detalhamento de qualidade não recompõe o FTT. O indicador vem da
        # mesma instância canônica usada pela visão gerencial, API, relatórios e IA.
        canonical_ftt = dict(
            (self.management.get_overview(filters).get("kpis") or {}).get("ftt") or {}
        )

        payload = {
            "periodo": filters.to_dict(),
            "totals": totals,
            "by_sector": [
                {"setor": key, **value}
                for key, value in sorted(by_sector.items(), key=lambda item: item[0].casefold())
            ],
            "by_product": [
                {"produto": key, **value}
                for key, value in sorted(by_product.items(), key=lambda item: item[0].casefold())
            ],
            "scrap_reasons": _rank_counts(scrap_reasons),
            "rework_reasons": _rank_counts(rework_reasons),
            "evidence": [
                {
                    "source": "eventos_quantidade_producao" if complete_source else "apontamentos_operacionais_fallback",
                    "event_id": event.get("id"),
                    "type": str(event.get("tipo") or "").strip().casefold(),
                    "quantity": max(0, int(event.get("quantidade") or 0)),
                    "sector": event.get("tipo_setor"),
                    "resource": event.get("recurso"),
                    "op": event.get("op"),
                    "operation": event.get("numero_operacao"),
                    "product": event.get("produto_codigo"),
                    "reason": event.get("motivo") or event.get("causa_raiz"),
                    "occurred_at": event.get("data_hora"),
                }
                for event in events
            ],
            "ftt": canonical_ftt,
            "availability": (
                DataAvailability.PARTIAL.value
                if complete_source
                else DataAvailability.INSUFFICIENT_DATA.value
            ),
            "reason": (
                "Eventos de quantidade são a fonte canônica. Retrabalho permanecerá parcial "
                "até a operação registrar sua quantidade explicitamente."
            ),
        }
        self._cache[cache_key] = payload
        return payload

    def standard_vs_actual(self, filters: AnalyticsFilter) -> dict:
        cache_key = ("standard_vs_actual", filters)
        if cache_key in self._cache:
            return self._cache[cache_key]
        rows = []
        rateio = self._rateio_allocation_map(filters)
        for fact in self._facts(filters):
            timeline = self._timeline(fact, filters)
            if timeline is None:
                continue
            standard_unit = _float_or_none(fact.get("tempo_medio_segundos"))
            good = int(fact.get("quantidade_boa") or 0)
            key = (
                str(fact.get("op") or "").strip().casefold(),
                str(fact.get("numero_operacao") or "").strip(),
            )
            if key in rateio:
                production_seconds = rateio[key]
                time_source = "rateio"
            elif timeline.has_event_data:
                production_seconds = timeline.seconds(EventCategory.PRODUCTION)
                time_source = "timeline_op"
            else:
                production_seconds = None
                time_source = "dados_insuficientes"
            real_per_piece = (
                production_seconds / good
                if production_seconds is not None and good > 0
                else None
            )
            expected = standard_unit * good if standard_unit is not None and good > 0 else None
            deviation = (
                production_seconds - expected
                if production_seconds is not None and expected is not None
                else None
            )
            rows.append({
                "apontamento_id": fact.get("id"),
                "op": fact.get("op"),
                "operacao": fact.get("numero_operacao"),
                "produto": fact.get("produto_codigo") or fact.get("peca"),
                "setor": fact.get("tipo_setor"),
                "recurso_previsto": fact.get("codigo_recurso"),
                "recurso_real": fact.get("maquina"),
                "quantidade_boa": good,
                "tempo_padrao_unitario_segundos": standard_unit,
                "tempo_padrao_estimado_segundos": expected,
                "tempo_producao_real_segundos": production_seconds,
                "fonte_tempo_producao": time_source,
                "tempo_real_por_peca_segundos": real_per_piece,
                "desvio_segundos": deviation,
                "desvio_percentual": (
                    deviation / expected * 100.0 if deviation is not None and expected else None
                ),
            })
        payload = {"periodo": filters.to_dict(), "items": rows}
        self._cache[cache_key] = payload
        return payload

    def chronoanalysis(self, filters: AnalyticsFilter) -> dict:
        samples = defaultdict(list)
        for row in self.standard_vs_actual(filters)["items"]:
            value = row.get("tempo_real_por_peca_segundos")
            if value is None:
                continue
            key = (
                str(row.get("produto") or "Não informado"),
                str(row.get("operacao") or "Não informada"),
                str(row.get("recurso_real") or "Não informado"),
            )
            samples[key].append(float(value))
        groups = []
        for (product, operation, resource), values in samples.items():
            groups.append({
                "produto": product,
                "operacao": operation,
                "recurso": resource,
                "amostras": len(values),
                "media_segundos_por_peca": mean(values),
                "mediana_segundos_por_peca": median(values),
                "minimo_segundos_por_peca": min(values),
                "maximo_segundos_por_peca": max(values),
                "desvio_padrao_segundos_por_peca": pstdev(values) if len(values) > 1 else 0.0,
            })
        groups.sort(key=lambda row: (row["produto"].casefold(), row["operacao"], row["recurso"].casefold()))
        return {"periodo": filters.to_dict(), "groups": groups}

    def planned_vs_actual(self, filters: AnalyticsFilter) -> dict:
        rows = []
        for fact in self._facts(filters):
            planned = (
                fact.get("quantidade_planejada_pcp")
                if fact.get("quantidade_planejada_pcp") is not None
                else fact.get("quantidade")
            )
            good = int(fact.get("quantidade_boa") or 0)
            scrap = int(fact.get("quantidade_refugo") or 0)
            rows.append({
                "apontamento_id": fact.get("id"),
                "op": fact.get("op"),
                "operacao": fact.get("numero_operacao"),
                "produto": fact.get("produto_codigo") or fact.get("peca"),
                "recurso_planejado": fact.get("codigo_recurso"),
                "recurso_real": fact.get("maquina"),
                "quantidade_planejada": planned,
                "quantidade_boa": good,
                "refugo": scrap,
                "retrabalho": int(fact.get("quantidade_retrabalho") or 0),
                "quantidade_atendida": ManufacturingRules.attended_quantity(good, scrap),
                "saldo_quantidade": (
                    ManufacturingRules.quantity_remaining(planned, good, scrap)
                    if planned is not None
                    else None
                ),
                "inicio_planejado": fact.get("inicio_planejado"),
                "fim_planejado": fact.get("fim_planejado"),
                "prazo_entrega": fact.get("prazo_entrega"),
                "inicio_real": fact.get("data_inicio"),
                "fim_real": fact.get("data_fim"),
                "prioridade": fact.get("prioridade"),
            })
        planning_complete = any(
            row.get("inicio_planejado") is not None or row.get("fim_planejado") is not None
            for row in rows
        )
        return {
            "periodo": filters.to_dict(),
            "items": rows,
            "planning_dates": {
                "availability": (
                    DataAvailability.PARTIAL.value if planning_complete
                    else DataAvailability.INSUFFICIENT_DATA.value
                ),
                "reason": "Datas planejadas dependem do preenchimento pelo ambiente corporativo.",
            },
        }

    def reliability(self, filters: AnalyticsFilter) -> dict:
        """Confiabilidade de equipamento — MTBF e MTTR sobre fatos reais.

        Definições industriais consolidadas (Symestic/Tulip/eMaint e a
        literatura de manutenção): ``MTBF = tempo operacional ÷ nº de falhas``
        e ``MTTR = tempo total de reparo ÷ nº de reparos concluídos``.

        O que conta como FALHA é decidido pela taxonomia já existente no
        Gestor (``ManufacturingRules.stop_reason_is_equipment_failure``), não
        por texto de motivo. Parada por falta de material, refeição, setup,
        espera ou parada programada nunca vira falha de equipamento.

        O tempo operacional usa a classificação produtiva canônica do Gestor
        (produção, setup e atividade sem OP), sobre o tempo físico já
        consolidado — nunca o tempo rateado às OPs.

        Sem catálogo de manutenção configurado, sem falhas no período ou sem
        tempo operacional medido, o indicador permanece explicitamente
        indisponível. Nenhum percentual é inventado.
        """

        cache_key = ("reliability", filters)
        if cache_key in self._cache:
            return self._cache[cache_key]

        catalog = self._stop_reason_catalog()
        failure_codes = {
            code for code, row in catalog.items()
            if ManufacturingRules.stop_reason_is_equipment_failure(row)
        }
        breakdown = self.time_breakdown(filters)
        totals = breakdown.get("totals") or {}
        operating_seconds = sum(
            float(totals.get(category.value) or 0.0)
            for category in EventCategory
            if ManufacturingRules.is_productive(category)
        )

        payload = {
            "periodo": filters.to_dict(),
            "mtbf_segundos": None,
            "mttr_segundos": None,
            "falhas": 0,
            "reparos_concluidos": 0,
            "tempo_operacional_segundos": operating_seconds,
            "tempo_reparo_segundos": 0.0,
            "por_recurso": [],
            "motivos": [],
            "taxonomia": (
                "Falha de equipamento é a parada classificada como manutenção "
                "corretiva no catálogo de motivos. Manutenção preventiva, "
                "espera, falta de material e setup não são falha."
            ),
            "availability": DataAvailability.NOT_CONFIGURED.value,
            "reason": (
                "Catálogo de motivos sem classe de manutenção corretiva: não há "
                "base para separar falha de equipamento de perda operacional."
            ),
        }
        if not catalog:
            self._cache[cache_key] = payload
            return payload
        if not failure_codes:
            self._cache[cache_key] = payload
            return payload

        failures = [
            row for row in self._segments(filters, EventCategory.DOWNTIME)
            # Uma parada marcada como programada não é falha, mesmo dentro do
            # grupo de manutenção: ela foi planejada.
            if str(row.get("codigo_status") or "").strip() in failure_codes
            and not row.get("programada")
        ]
        repairs = [row for row in failures if not row.get("em_andamento")]
        repair_seconds = sum(float(row.get("segundos") or 0.0) for row in repairs)

        by_resource = defaultdict(lambda: {"falhas": 0, "segundos": 0.0})
        reason_counts = defaultdict(int)
        for row in failures:
            resource = str(row.get("recurso") or "Não informado")
            by_resource[resource]["falhas"] += 1
            by_resource[resource]["segundos"] += float(row.get("segundos") or 0.0)
            reason_counts[str(row.get("motivo") or "Não informado")] += 1

        payload.update({
            "falhas": len(failures),
            "reparos_concluidos": len(repairs),
            "tempo_reparo_segundos": repair_seconds,
            "mttr_segundos": repair_seconds / len(repairs) if repairs else None,
            "mtbf_segundos": (
                operating_seconds / len(failures)
                if failures and operating_seconds > 0
                else None
            ),
            "por_recurso": [
                {
                    "recurso": resource,
                    "falhas": value["falhas"],
                    "tempo_reparo_segundos": value["segundos"],
                    "mttr_segundos": (
                        value["segundos"] / value["falhas"] if value["falhas"] else None
                    ),
                }
                for resource, value in sorted(
                    by_resource.items(),
                    key=lambda item: (-item[1]["falhas"], item[0].casefold()),
                )
            ],
            "motivos": _rank_counts(reason_counts),
        })

        if not failures:
            payload["availability"] = DataAvailability.NO_RECORDS.value
            payload["reason"] = "Nenhuma falha de equipamento registrada no período."
        elif operating_seconds <= 0:
            payload["availability"] = DataAvailability.PARTIAL.value
            payload["reason"] = (
                "Falhas registradas sem tempo operacional medido no período: "
                "o MTBF depende do tempo físico produtivo."
            )
        else:
            payload["availability"] = DataAvailability.AVAILABLE.value
            payload["reason"] = (
                f"{len(failures)} falha(s) de equipamento sobre "
                f"{operating_seconds / 3600.0:.1f} h de tempo operacional."
            )
        self._cache[cache_key] = payload
        return payload

    def _stop_reason_catalog(self):
        cache_key = ("stop_reason_catalog",)
        if cache_key in self._cache:
            return self._cache[cache_key]
        loader = getattr(self.db, "listar_status_recursos", None)
        rows = list(loader(incluir_ocultos=True) or []) if callable(loader) else []
        catalog = {
            str(row.get("codigo") or "").strip(): dict(row)
            for row in rows
            if str(row.get("codigo") or "").strip()
        }
        self._cache[cache_key] = catalog
        return catalog

    def capacity_configuration(self, filters: AnalyticsFilter) -> dict:
        """Capacidade e utilização temporal do recurso no período.

        Wave 2: a base real da capacidade é o **calendário produtivo** já
        cadastrado (``calendarios_produtivos`` / ``turnos_produtivos`` /
        exceções). O tempo disponível vem de ``CalendarService`` e a carga vem
        do tempo físico consolidado — nunca do tempo rateado às OPs, que
        multiplicaria a máquina por OPs simultâneas.

        Isto é **utilização temporal** (a base do TEEP: quanto do tempo
        disponível virou trabalho) e é rotulado como tal. Capacidade em PEÇAS
        exigiria tempo padrão/ciclo ideal confiável por operação, que o Gestor
        ainda não possui de forma completa; por isso ela não é publicada.

        Recurso sem calendário permanece ``nao_configurado``. Nenhum número é
        estimado para preencher a tela.
        """

        loader = getattr(self.db, "listar_configuracao_capacidade_recursos", None)
        if not callable(loader):
            return {
                "periodo": filters.to_dict(),
                "items": [],
                "unidade": "tempo",
                "availability": DataAvailability.NOT_CONFIGURED.value,
                "reason": "Repository atual não expõe configuração de capacidade.",
            }
        rows = list(loader(setor=filters.setor, recurso=filters.recurso) or [])
        if not rows:
            return {
                "periodo": filters.to_dict(),
                "items": [],
                "unidade": "tempo",
                "availability": DataAvailability.NOT_CONFIGURED.value,
                "reason": "Nenhum recurso habilitado no filtro selecionado.",
            }

        calendar = CalendarService(self.db, self.rules)
        breakdown = self.time_breakdown(filters)
        by_resource = {
            str(item.get("recurso") or "").strip().casefold(): item
            for item in breakdown.get("by_resource", [])
        }
        queue_by_resource = defaultdict(int)
        planned_by_resource = defaultdict(float)
        for fact in self._facts(filters):
            key = str(fact.get("maquina") or "").strip().casefold()
            planned_by_resource[key] += max(
                0.0,
                float(
                    fact.get("quantidade_planejada_pcp")
                    if fact.get("quantidade_planejada_pcp") is not None
                    else fact.get("quantidade") or 0
                ),
            )
            if str(fact.get("status") or "") == "Aguardando":
                queue_by_resource[key] += 1

        items = []
        com_calendario = 0
        for raw in rows:
            item = dict(raw)
            code = str(item.get("codigo") or item.get("nome") or "").strip()
            key = code.casefold()
            # Capacidade é a disponibilidade PLANEJADA no período selecionado,
            # não um cronômetro de disponibilidade já transcorrida. Usar
            # ``agora`` como fim fazia cada segundo ser somado uma vez por
            # recurso com calendário; no total da fábrica, poucos segundos
            # reais viravam vários minutos e a tela publicava um valor móvel.
            summary = calendar.period_summary(code, filters.inicio, filters.fim)
            available = summary.get("tempo_disponivel_segundos")
            time_row = by_resource.get(key, {})
            # Carga = tempo físico em que o recurso esteve ocupado. Setup e
            # retrabalho ocupam a máquina, então entram na ocupação.
            load = sum(
                float(time_row.get(category) or 0.0)
                for category in ("producao", "setup", "retrabalho")
            )
            item.update({
                "capacidade_segundos": None if available is None else float(available),
                "capacidade_unidade": "h no período",
                "carga_segundos": load,
                "capacidade_restante_segundos": (
                    None if available is None else max(0.0, float(available) - load)
                ),
                "utilizacao_percentual": (
                    load / float(available) * 100.0
                    if available is not None and float(available) > 0
                    else None
                ),
                "calendario_availability": summary.get("availability"),
                "calendario_reason": summary.get("reason"),
                "fila": queue_by_resource[key],
                "quantidade_planejada": planned_by_resource[key],
            })
            if available is not None:
                com_calendario += 1
            items.append(item)

        com_utilizacao = [
            item for item in items if item.get("utilizacao_percentual") is not None
        ]
        ranked = sorted(
            com_utilizacao,
            key=lambda item: (
                float(item.get("utilizacao_percentual") or 0.0),
                int(item.get("fila") or 0),
            ),
            reverse=True,
        )
        total_capacity = sum(
            float(item.get("capacidade_segundos") or 0.0) for item in items
        )
        total_load = sum(
            float(item.get("carga_segundos") or 0.0)
            for item in items
            if item.get("capacidade_segundos") is not None
        )
        if com_calendario == len(items):
            availability = DataAvailability.AVAILABLE.value
            reason = (
                "Utilização temporal sobre o calendário produtivo cadastrado: "
                "tempo ocupado dividido pelo tempo disponível no período."
            )
        elif com_calendario:
            availability = DataAvailability.PARTIAL.value
            reason = (
                f"{len(items) - com_calendario} de {len(items)} recursos ainda "
                "não possuem calendário/turno produtivo cadastrado."
            )
        else:
            availability = DataAvailability.NOT_CONFIGURED.value
            reason = (
                "Nenhum recurso do filtro possui calendário/turno produtivo "
                "cadastrado: sem ele não existe tempo disponível para comparar."
            )
        return {
            "periodo": filters.to_dict(),
            "items": items,
            # Grandeza publicada: tempo, não peças. Capacidade em peças exige
            # tempo padrão confiável por operação e não é estimada aqui.
            "unidade": "tempo",
            "availability": availability,
            "reason": reason,
            "recursos": len(items),
            "recursos_com_calendario": com_calendario,
            "recursos_sem_calendario": len(items) - com_calendario,
            "total_capacity_seconds": total_capacity if com_calendario else None,
            "total_load_seconds": total_load if com_calendario else None,
            "total_remaining_seconds": (
                max(0.0, total_capacity - total_load) if com_calendario else None
            ),
            "utilizacao_percentual": (
                total_load / total_capacity * 100.0
                if com_calendario and total_capacity > 0
                else None
            ),
            "bottleneck_resource": (
                (ranked[0].get("codigo") or ranked[0].get("nome")) if ranked else None
            ),
            "bottleneck_utilizacao_percentual": (
                ranked[0].get("utilizacao_percentual") if ranked else None
            ),
        }

    def _segment_summary(self, filters, rows, *, label):
        physical = _consolidate_labeled_rows(rows)
        return {
            "periodo": filters.to_dict(),
            "count": len(rows),
            "total_seconds": physical["physical_seconds"],
            "raw_attributed_seconds": physical["raw_attributed_seconds"],
            "overlap_removed_seconds": physical["overlap_removed_seconds"],
            "conflicting_label_seconds": physical["conflicting_label_seconds"],
            "items": rows,
            "by_reason": _rank_seconds(physical["by_reason"]),
            "by_resource": _rank_seconds(physical["by_resource"], key_name="recurso"),
            "kind": label,
        }

    def _segments(self, filters, category):
        cache_key = ("segments", filters, category)
        if cache_key in self._cache:
            return self._cache[cache_key]
        # Para visões fabris/recurso, a existência da timeline física canônica
        # é suficiente para ela ser a fonte de verdade, mesmo que não exista
        # nenhum segmento da categoria pedida. Nesse caso retornar [] é correto;
        # cair para a timeline por OP poderia reintroduzir estados conflitantes ou
        # duplicados que o estado físico já resolveu.
        #
        # Em filtros por OP/operação, o vínculo físico pode ser intencionalmente
        # nulo quando há execução simultânea. Nessa granularidade, o fallback por
        # OP continua permitido para investigação/rastreabilidade.
        if not filters.op and filters.operacao is None:
            state_source_available, all_state_rows = self._resource_states(filters)
            if state_source_available and all_state_rows:
                state_rows = [
                    row for row in all_state_rows
                    if str(row.get("categoria") or "").strip() == category.value
                ]
            else:
                state_rows = []
        else:
            state_source_available, state_rows = self._resource_states(filters, category=category)

        if state_source_available and (state_rows or (not filters.op and filters.operacao is None)):
            rows = []
            for state in state_rows:
                start = _dt(state.get("inicio_periodo") or state.get("data_inicio"))
                end = _dt(state.get("fim_periodo") or state.get("data_fim")) or filters.fim
                if start is None or end <= start:
                    continue
                rows.append({
                    "apontamento_id": state.get("apontamento_id"),
                    "evento_id": state.get("evento_apontamento_id"),
                    "estado_recurso_id": state.get("id"),
                    "op": state.get("op"),
                    "operacao": state.get("numero_operacao"),
                    "produto": state.get("produto_codigo"),
                    "setor": str(state.get("tipo_setor") or "Não informado"),
                    "recurso": str(state.get("recurso") or "Não informado"),
                    "inicio": start,
                    "fim": end,
                    "segundos": max(0.0, (end - start).total_seconds()),
                    "codigo_status": state.get("codigo_status_recurso"),
                    "motivo": str(state.get("motivo") or state.get("codigo_status_recurso") or "Não informado"),
                    "programada": state.get("planejado"),
                    "automatica": bool(state.get("automatico")),
                    "tipo_interrupcao": state.get("tipo_interrupcao"),
                    "tipo_setup": None,
                    "fonte": "eventos_estado_recurso",
                    "em_andamento": state.get("data_fim") is None,
                })
            rows.sort(key=lambda row: (row["inicio"], row.get("estado_recurso_id") or 0))
            self._cache[cache_key] = rows
            return rows

        rows = []
        for fact in self._facts(filters):
            timeline = self._timeline(fact, filters)
            if timeline is None:
                continue
            for segment in timeline.segments:
                if segment.category != category:
                    continue
                rows.append({
                    "apontamento_id": fact.get("id"),
                    "evento_id": segment.source_event_id,
                    "estado_recurso_id": None,
                    "op": fact.get("op"),
                    "operacao": fact.get("numero_operacao"),
                    "produto": fact.get("produto_codigo") or fact.get("peca"),
                    "setor": str(fact.get("tipo_setor") or "Não informado"),
                    "recurso": str(fact.get("maquina") or "Não informado"),
                    "inicio": segment.start,
                    "fim": segment.end,
                    "segundos": segment.seconds,
                    "codigo_status": segment.status_code,
                    "motivo": str(segment.reason or segment.status_code or "Não informado"),
                    "programada": bool(segment.planned),
                    "automatica": bool(segment.automatic),
                    "tipo_interrupcao": segment.interruption_type,
                    "tipo_setup": fact.get("tipo_setup") if category == EventCategory.SETUP else None,
                    "fonte": "timeline_apontamento_fallback",
                    "em_andamento": (
                        fact.get("data_fim") is None
                        and segment.end == min(self._now(), filters.fim)
                    ),
                })
        rows.sort(key=lambda row: (row["inicio"], row.get("evento_id") or 0))
        self._cache[cache_key] = rows
        return rows

    def _timeline(self, row, filters):
        start = _dt(row.get("data_inicio"))
        if start is None:
            return None
        end = _dt(row.get("data_fim")) or min(self._now(), filters.fim)
        clip_start = max(start, filters.inicio)
        clip_end = min(end, filters.fim)
        if clip_end <= clip_start:
            return None
        return build_operator_timeline(row.get("eventos") or [], start=clip_start, end=clip_end)

    def _facts(self, filters):
        cache_key = ("facts", filters)
        if cache_key in self._cache:
            return self._cache[cache_key]
        loader = getattr(self.db, "listar_fatos_operacionais_periodo", None)
        if not callable(loader):
            return []
        rows = list(loader(
            filters.inicio, filters.fim,
            setor=filters.setor, recurso=filters.recurso, op=filters.op,
            operacao=filters.operacao, produto=filters.produto, operador=filters.operador,
        ) or [])
        self._cache[cache_key] = rows
        return rows

    def _quantity_events(self, filters):
        cache_key = ("quantity_events", filters)
        if cache_key in self._cache:
            return self._cache[cache_key]
        loader = getattr(self.db, "listar_eventos_quantidade_periodo", None)
        if callable(loader):
            payload = (list(loader(
                filters.inicio, filters.fim,
                setor=filters.setor, recurso=filters.recurso, op=filters.op,
                operacao=filters.operacao, produto=filters.produto, operador=filters.operador,
            ) or []), True)
            self._cache[cache_key] = payload
            return payload
        events = []
        for fact in self._facts(filters):
            for kind, field in (("boa", "quantidade_boa"), ("refugo", "quantidade_refugo"), ("retrabalho", "quantidade_retrabalho")):
                qty = int(fact.get(field) or 0)
                if qty > 0:
                    events.append({
                        "tipo": kind, "quantidade": qty, "op": fact.get("op"),
                        "numero_operacao": fact.get("numero_operacao"),
                        "produto_codigo": fact.get("produto_codigo"),
                        "recurso": fact.get("maquina"), "tipo_setor": fact.get("tipo_setor"),
                        "motivo": fact.get("motivo_refugo") if kind == "refugo" else None,
                    })
        payload = (events, False)
        self._cache[cache_key] = payload
        return payload

    def _rateio_allocation_map(self, filters):
        cache_key = ("rateio", filters)
        if cache_key in self._cache:
            return self._cache[cache_key]
        loader = getattr(self.db, "listar_rateios_tempo_periodo", None)
        if not callable(loader):
            return {}
        sessions = list(loader(
            filters.inicio, filters.fim,
            setor=filters.setor, recurso=filters.recurso, op=filters.op,
            operacao=filters.operacao,
        ) or [])
        result = defaultdict(float)
        for session in sessions:
            for item in session.get("rateios") or []:
                key = (
                    str(item.get("op") or "").strip().casefold(),
                    str(item.get("numero_operacao") or "").strip(),
                )
                result[key] += float(item.get("segundos_atribuidos_periodo") or 0)
        payload = dict(result)
        self._cache[cache_key] = payload
        return payload

    def _resource_states(self, filters, category=None):
        category_value = category.value if isinstance(category, EventCategory) else category
        cache_key = ("resource_states", filters, category_value)
        if cache_key in self._cache:
            return self._cache[cache_key]
        loader = getattr(self.db, "listar_estados_recurso_periodo", None)
        if not callable(loader):
            return False, []
        rows = loader(
            filters.inicio,
            filters.fim,
            setor=filters.setor,
            recurso=filters.recurso,
            categoria=category_value,
            op=filters.op,
            operacao=filters.operacao,
        )
        payload = (True, list(rows or []))
        self._cache[cache_key] = payload
        return payload

    def _nestings(self, filters):
        cache_key = ("nestings", filters)
        if cache_key in self._cache:
            return self._cache[cache_key]
        if filters.setor and str(filters.setor).strip().casefold() != "corte":
            return []
        if any((filters.op, filters.operacao, filters.produto, filters.turno, filters.operador)):
            return []
        loader = getattr(self.db, "listar_tempos_nesting_corte", None)
        if not callable(loader):
            return []
        rows = list(loader(inicio=filters.inicio, fim=filters.fim, maquina=filters.recurso) or [])
        self._cache[cache_key] = rows
        return rows



def _consolidate_labeled_rows(rows):
    """Consolida paradas/setups por recurso sem duplicar OPs simultâneas.

    Quando duas OPs registram o mesmo motivo no mesmo recurso/instante, o tempo
    entra uma única vez. Motivos diferentes simultâneos são mantidos como conflito
    de classificação, pois escolher uma causa sem evidência corromperia o Pareto.
    """

    by_group = defaultdict(list)
    raw_total = 0.0
    for index, row in enumerate(rows or []):
        start = _dt(row.get("inicio"))
        end = _dt(row.get("fim"))
        if start is None or end is None or end <= start:
            continue
        resource = str(row.get("recurso") or "Não informado").strip() or "Não informado"
        key = resource.casefold()
        if key == "não informado".casefold():
            key = f"__desconhecido__:{index}"
        by_group[key].append((index, row, start, end, resource))
        raw_total += max(0.0, (end - start).total_seconds())

    by_reason = defaultdict(float)
    by_resource = defaultdict(float)
    physical_total = 0.0
    conflict_total = 0.0

    for group in by_group.values():
        events = []
        for local_index, (_original, _row, start, end, _resource) in enumerate(group):
            events.append((start, 1, local_index))
            events.append((end, 0, local_index))
        events.sort(key=lambda item: (item[0], item[1]))

        active = set()
        previous = None
        cursor = 0
        while cursor < len(events):
            timestamp = events[cursor][0]
            if previous is not None and timestamp > previous and active:
                seconds = (timestamp - previous).total_seconds()
                active_rows = [group[i][1] for i in sorted(active)]
                resources = {str(row.get("recurso") or "Não informado") for row in active_rows}
                resource = next(iter(resources)) if len(resources) == 1 else "Não informado"
                reasons = {str(row.get("motivo") or "Não informado") for row in active_rows}
                if len(reasons) == 1:
                    reason = next(iter(reasons))
                else:
                    reason = "Conflito de classificação"
                    conflict_total += seconds
                physical_total += seconds
                by_resource[resource] += seconds
                by_reason[reason] += seconds

            same_time = []
            while cursor < len(events) and events[cursor][0] == timestamp:
                same_time.append(events[cursor])
                cursor += 1
            for _time, kind, local_index in same_time:
                if kind == 0:
                    active.discard(local_index)
            for _time, kind, local_index in same_time:
                if kind == 1:
                    active.add(local_index)
            previous = timestamp

    return {
        "physical_seconds": physical_total,
        "raw_attributed_seconds": raw_total,
        "overlap_removed_seconds": max(0.0, raw_total - physical_total),
        "conflicting_label_seconds": conflict_total,
        "by_reason": dict(by_reason),
        "by_resource": dict(by_resource),
    }

def _category_dict(values):
    return {category.value: float(values.get(category, 0.0)) for category in EventCategory}


def _rank_seconds(mapping, key_name="motivo"):
    return [
        {key_name: key, "segundos": seconds}
        for key, seconds in sorted(mapping.items(), key=lambda item: (-item[1], item[0].casefold()))
    ]


def _rank_counts(mapping):
    return [
        {"motivo": key, "quantidade": value}
        for key, value in sorted(mapping.items(), key=lambda item: (-item[1], item[0].casefold()))
    ]


def _float_or_none(value):
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _dt(value):
    if value is None or isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
