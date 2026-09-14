"""Operational query and report calculations for the MES."""

from datetime import datetime, timedelta
import logging

from app.core.formatting import format_datetime_text, parse_datetime_text
from mes.analytics.timeline import build_operator_timeline
from mes.domain import EventCategory

MOVEMENT_TYPE = "Movimentação"
DEFAULT_STATUS_LIMITS = (
    (4, "Normal"),
    (8, "Atenção"),
    (24, "Atrasado"),
    (None, "Crítico"),
)


class OperationalReportService:
    """Mantém consultas e cálculos MES independentes da apresentação Web."""

    def __init__(
        self,
        db,
        status_limits=None,
        maquinas_dobra=None,
        maquinas_usinagem=None,
        now_func=None,
        maquinas_serra=None,
    ):
        self.db = db
        self.status_limits = tuple(status_limits or DEFAULT_STATUS_LIMITS)
        self.maquinas_dobra = list(maquinas_dobra or [])
        self.maquinas_usinagem = list(maquinas_usinagem or [])
        self.maquinas_serra = list(maquinas_serra or [])
        self._now_func = now_func or datetime.now

    def parse_data_operacional(self, valor):
        return parse_datetime_text(valor)

    def formatar_data_operacional(self, valor):
        return format_datetime_text(valor)

    def formatar_duracao_operacional(self, inicio, fim=None):
        inicio_dt = self.parse_data_operacional(inicio)
        if not inicio_dt:
            return "", None
        fim_dt = fim or self._now()
        segundos = max(0, int((fim_dt - inicio_dt).total_seconds()))
        texto = self.formatar_segundos_operacional(segundos, incluir_minutos_em_dias=True)
        return texto, segundos / 3600

    def status_tempo_operacional(self, horas):
        if horas is None:
            return ""
        for limite, status in self.status_limits:
            if limite is None or horas <= limite:
                return status
        return self.status_limits[-1][1] if self.status_limits else ""

    def tempo_no_setor_atual(self, data_hora):
        texto, horas = self.formatar_duracao_operacional(data_hora)
        return texto, horas, self.status_tempo_operacional(horas)

    def codigo_tarefa_linha(self, registro, cache=None):
        tarefa_id = registro.get("tarefa_id") if isinstance(registro, dict) else None
        if not tarefa_id:
            return ""
        if cache is not None and tarefa_id in cache:
            return cache[tarefa_id]
        try:
            tarefa = self.db.buscar_tarefa_por_id(tarefa_id)
            codigo = tarefa["codigo_tarefa"] if tarefa else ""
        except Exception:
            logging.exception("Erro ao buscar tarefa vinculada")
            codigo = ""
        if cache is not None:
            cache[tarefa_id] = codigo
        return codigo

    def enriquecer_op_operacional(self, registro, cache_tarefas=None):
        item = dict(registro)
        tempo, horas, status_tempo = self.tempo_no_setor_atual(item.get("data_hora"))
        item["tarefa"] = self.codigo_tarefa_linha(item, cache_tarefas)
        item["ultima_movimentacao"] = self.formatar_data_operacional(item.get("data_hora"))
        item["entrada_setor"] = item["ultima_movimentacao"]
        item["tempo_setor"] = tempo
        item["horas_setor"] = horas
        item["status_tempo"] = status_tempo
        return item

    def obter_ops_movimento_enriquecidas(self, setor_filter=None, search=None):
        rows = self.db.get_current_ops(
            setor_filter=setor_filter,
            search=search,
            maquinas_dobra=self.maquinas_dobra,
            maquinas_usinagem=self.maquinas_usinagem,
            maquinas_serra=self.maquinas_serra,
        )
        cache_tarefas = {}
        return [self.enriquecer_op_operacional(row, cache_tarefas) for row in rows]

    def segundos_entre_datas(self, inicio, fim):
        inicio_dt = self.parse_data_operacional(inicio)
        fim_dt = self.parse_data_operacional(fim)
        if not inicio_dt or not fim_dt:
            return None
        return max(0, int((fim_dt - inicio_dt).total_seconds()))

    def formatar_segundos_operacional(self, segundos, incluir_minutos_em_dias=False):
        if segundos is None:
            return ""
        segundos = max(0, int(segundos))
        minutos = segundos // 60
        horas = minutos // 60
        mins = minutos % 60
        dias = horas // 24
        horas_restantes = horas % 24
        if dias:
            texto = f"{dias}d {horas_restantes}h"
            if incluir_minutos_em_dias and mins and dias < 2:
                texto += f"{mins:02d}min"
            return texto
        if horas:
            return f"{horas}h{mins:02d}min"
        return f"{mins}min"

    def media_segundos(self, valores):
        valores_validos = [v for v in valores if v is not None]
        if not valores_validos:
            return None
        return sum(valores_validos) / len(valores_validos)

    def dentro_periodo_tempos(self, valor, inicio, fim):
        dt = self.parse_data_operacional(valor)
        return bool(dt and inicio <= dt <= fim)

    def calcular_relatorio_tempos_setor(self, inicio, fim, tipo_setor):
        """Calcula tempo real entre Início e Finalizar para um setor produtivo."""

        fact_loader = getattr(self.db, "listar_fatos_operacionais_periodo", None)
        if callable(fact_loader):
            apontamentos = fact_loader(inicio, fim, setor=tipo_setor)
        else:
            apontamentos = self.db.listar_apontamentos_operacionais_periodo(tipo_setor, inicio, fim)
        agora_periodo = min(self._now(), fim)
        rateio_map = {}
        rateio_loader = getattr(self.db, "listar_rateios_tempo_periodo", None)
        if callable(rateio_loader):
            for session in rateio_loader(inicio, fim, setor=tipo_setor) or []:
                for allocation in session.get("rateios") or []:
                    key = (
                        str(allocation.get("op") or "").strip().casefold(),
                        str(allocation.get("numero_operacao") or "").strip(),
                    )
                    rateio_map[key] = rateio_map.get(key, 0.0) + float(
                        allocation.get("segundos_atribuidos_periodo") or 0
                    )
        etapas_stats = {}
        op_rows = []
        duracoes = []
        ops_unicas = set()
        em_processo = 0
        tarefas_cache = {}

        for item in apontamentos:
            data_inicio = self.parse_data_operacional(item.get("data_inicio"))
            if not data_inicio:
                continue
            data_fim = self.parse_data_operacional(item.get("data_fim"))
            recorte_inicio = max(data_inicio, inicio)
            recorte_fim = min(data_fim or agora_periodo, fim)
            lead_seconds = max(0, int((recorte_fim - recorte_inicio).total_seconds()))
            timeline = build_operator_timeline(
                item.get("eventos") or (),
                start=recorte_inicio,
                end=recorte_fim,
            )
            key_rateio = (
                str(item.get("op") or "").strip().casefold(),
                str(item.get("numero_operacao") or "").strip(),
            )
            if key_rateio in rateio_map:
                segundos = int(round(rateio_map[key_rateio]))
                producao_seg = segundos
                fonte_tempo = "rateio"
                parada_seg = int(timeline.seconds(EventCategory.DOWNTIME)) if timeline.has_event_data else 0
                setup_seg = int(timeline.seconds(EventCategory.SETUP)) if timeline.has_event_data else 0
                retrabalho_seg = int(timeline.seconds(EventCategory.REWORK)) if timeline.has_event_data else 0
            elif timeline.has_event_data:
                segundos = int(timeline.seconds(EventCategory.PRODUCTION))
                producao_seg = segundos
                fonte_tempo = "timeline_op"
                parada_seg = int(timeline.seconds(EventCategory.DOWNTIME))
                setup_seg = int(timeline.seconds(EventCategory.SETUP))
                retrabalho_seg = int(timeline.seconds(EventCategory.REWORK))
            else:
                # Não transforma lead time em produção. Sem eventos/rateio, a
                # duração produtiva da OP é desconhecida.
                segundos = 0
                producao_seg = 0
                fonte_tempo = "dados_insuficientes"
                parada_seg = setup_seg = retrabalho_seg = 0
            maquina = item.get("maquina") or tipo_setor
            aberto = item.get("status") in {"Em processo", "Parada", "Setup", "Retrabalho"} and data_fim is None
            if aberto:
                em_processo += 1
            duracoes.append(lead_seconds)
            ops_unicas.add(item.get("op") or "")

            stats = etapas_stats.setdefault(maquina, {"qtd": 0, "total": 0, "maior": 0, "abertas": 0})
            stats["qtd"] += 1
            stats["total"] += segundos
            stats["maior"] = max(stats["maior"], segundos)
            if aberto:
                stats["abertas"] += 1

            tarefa_codigo = self.codigo_tarefa_linha(item, tarefas_cache)

            op_rows.append({
                "op": item.get("op") or "",
                "peca": item.get("peca") or "",
                "tarefa": tarefa_codigo,
                "setor_atual": maquina,
                "movimentacoes": 1,
                "tempo_total_seg": segundos,
                "tempo_total": self.formatar_segundos_operacional(segundos),
                "lead_time_seg": lead_seconds,
                "lead_time": self.formatar_segundos_operacional(lead_seconds),
                "tempo_produtivo_seg": producao_seg,
                "tempo_produtivo": self.formatar_segundos_operacional(producao_seg),
                "fonte_tempo_produtivo": fonte_tempo,
                "tempo_parada_seg": parada_seg,
                "tempo_parada": self.formatar_segundos_operacional(parada_seg),
                "tempo_setup_seg": setup_seg,
                "tempo_setup": self.formatar_segundos_operacional(setup_seg),
                "tempo_retrabalho_seg": retrabalho_seg,
                "tempo_retrabalho": self.formatar_segundos_operacional(retrabalho_seg),
                "tempo_aberto_seg": segundos if aberto else None,
                "tempo_aberto": self.formatar_segundos_operacional(segundos if aberto else None),
                "status_tempo": self.status_tempo_operacional(segundos / 3600) if aberto else "Finalizado",
                "status_processo": item.get("status") or "",
                "inicio": self.formatar_data_operacional(item.get("data_inicio")),
                "fim": self.formatar_data_operacional(item.get("data_fim")),
                "destino": item.get("setor_destino") or "",
            })

        etapa_rows = []
        for maquina, stats in etapas_stats.items():
            media = stats["total"] / stats["qtd"] if stats["qtd"] else 0
            etapa_rows.append({
                "setor": maquina,
                "etapas": stats["qtd"],
                "tempo_medio_seg": media,
                "tempo_medio": self.formatar_segundos_operacional(media),
                "maior_tempo_seg": stats["maior"],
                "maior_tempo": self.formatar_segundos_operacional(stats["maior"]),
                "tempo_total_seg": stats["total"],
                "tempo_total": self.formatar_segundos_operacional(stats["total"]),
                "abertas": stats["abertas"],
            })
        etapa_rows.sort(key=lambda row: row["tempo_medio_seg"], reverse=True)
        op_rows.sort(key=lambda row: row["tempo_total_seg"], reverse=True)

        indicadores = {
            "tarefas": len(apontamentos),
            "lead_medio": self.formatar_segundos_operacional(self.media_segundos(duracoes)),
            "destaque_medio": self.formatar_segundos_operacional(sum(duracoes)),
            "pallet_medio": self.formatar_segundos_operacional(max(duracoes) if duracoes else None),
            "tempo_medio_etapa": self.formatar_segundos_operacional(self.media_segundos(duracoes)),
            "ops": len({op for op in ops_unicas if op}),
            "ops_criticas": em_processo,
        }
        return {
            "visao": tipo_setor,
            "indicadores": indicadores,
            "etapas": etapa_rows,
            "tarefas": [],
            "ops": op_rows,
        }

    def calcular_relatorio_tempos_mes(self, inicio, fim, setor_filtro=None):
        setor_filtro_norm = (setor_filtro or "").strip().upper()
        categoria_setor = setor_filtro_norm if setor_filtro_norm in ("DOBRA", "USINAGEM", "SERRA") else ""
        if categoria_setor and hasattr(self.db, "listar_apontamentos_operacionais_periodo"):
            resultado_setor = self.calcular_relatorio_tempos_setor(inicio, fim, categoria_setor.title())
            if resultado_setor["ops"]:
                return resultado_setor
        somente_tarefas = setor_filtro_norm == "TAREFAS"
        if somente_tarefas:
            setor_filtro_norm = ""
        setores_categoria = set()
        if categoria_setor == "DOBRA":
            setores_categoria = {"DOBRA", "AGUARDANDO DOBRA", *(str(item).strip().upper() for item in self.maquinas_dobra)}
        elif categoria_setor == "USINAGEM":
            setores_categoria = {"USINAGEM", "AGUARDANDO USINAGEM", *(str(item).strip().upper() for item in self.maquinas_usinagem)}
        elif categoria_setor == "SERRA":
            setores_categoria = {"SERRA", "AGUARDANDO SERRA", *(str(item).strip().upper() for item in self.maquinas_serra)}
        historico = self.db.obter_historico_completo(
            periodo_inicio=inicio,
            periodo_fim=fim,
            tipo=MOVEMENT_TYPE,
        )
        movimentos = []
        for row in historico:
            if str(row.get("op") or "").upper().startswith("T"):
                continue
            data_dt = self.parse_data_operacional(row.get("data_hora"))
            if not data_dt:
                continue
            movimentos.append({**row, "_data_dt": data_dt})
        movimentos.sort(key=lambda item: (item.get("op") or "", item["_data_dt"]))

        por_op = {}
        for mov in movimentos:
            por_op.setdefault(mov.get("op") or "", []).append(mov)

        etapas_stats = {}
        op_rows = []
        agora = self._now()
        tarefas_cache = {}
        for op, eventos in por_op.items():
            total_seg = 0
            peca = ""
            tarefa_codigo = ""
            setor_atual = ""
            aberto_seg = None
            for idx, ev in enumerate(eventos):
                setor = ev.get("setor") or ""
                if setores_categoria and setor.upper() not in setores_categoria:
                    continue
                if setor_filtro_norm and not categoria_setor and setor_filtro_norm not in setor.upper():
                    continue
                prox = eventos[idx + 1]["_data_dt"] if idx + 1 < len(eventos) else agora
                segundos = max(0, int((prox - ev["_data_dt"]).total_seconds()))
                total_seg += segundos
                peca = ev.get("peca") or peca
                tarefa_codigo = self.codigo_tarefa_linha(ev, tarefas_cache) or tarefa_codigo
                setor_atual = setor or setor_atual
                aberto = idx + 1 == len(eventos)
                if aberto:
                    aberto_seg = segundos
                stats = etapas_stats.setdefault(setor or "Sem setor", {"qtd": 0, "total": 0, "maior": 0, "abertas": 0})
                stats["qtd"] += 1
                stats["total"] += segundos
                stats["maior"] = max(stats["maior"], segundos)
                if aberto:
                    stats["abertas"] += 1

            if total_seg or not setor_filtro_norm:
                status_aberto = self.status_tempo_operacional((aberto_seg or 0) / 3600) if aberto_seg is not None else ""
                op_rows.append({
                    "op": op,
                    "peca": peca,
                    "tarefa": tarefa_codigo,
                    "setor_atual": setor_atual,
                    "movimentacoes": len(eventos),
                    "tempo_total_seg": total_seg,
                    "tempo_total": self.formatar_segundos_operacional(total_seg),
                    "tempo_aberto_seg": aberto_seg,
                    "tempo_aberto": self.formatar_segundos_operacional(aberto_seg),
                    "status_tempo": status_aberto,
                })

        etapa_rows = []
        for setor, stats in etapas_stats.items():
            media = stats["total"] / stats["qtd"] if stats["qtd"] else 0
            etapa_rows.append({
                "setor": setor,
                "etapas": stats["qtd"],
                "tempo_medio_seg": media,
                "tempo_medio": self.formatar_segundos_operacional(media),
                "maior_tempo_seg": stats["maior"],
                "maior_tempo": self.formatar_segundos_operacional(stats["maior"]),
                "tempo_total_seg": stats["total"],
                "tempo_total": self.formatar_segundos_operacional(stats["total"]),
                "abertas": stats["abertas"],
            })
        etapa_rows.sort(key=lambda item: item["tempo_medio_seg"], reverse=True)
        op_rows.sort(key=lambda item: item["tempo_aberto_seg"] or 0, reverse=True)

        tarefa_rows = []
        tarefas = list(self.db.get_tasks())
        try:
            contagens_ops = self.db.get_op_counts_by_task(
                tarefa.get("id") for tarefa in tarefas if tarefa.get("id") is not None
            )
        except Exception:
            logging.exception("Erro ao contar OPs no relatorio de tempos")
            contagens_ops = {}
        for tarefa in tarefas:
            inicio_destaque = tarefa.get("data_inicio_destaque")
            finalizacao = tarefa.get("data_finalizacao")
            despacho = tarefa.get("data_despacho")
            if not (
                self.dentro_periodo_tempos(inicio_destaque, inicio, fim)
                or self.dentro_periodo_tempos(finalizacao, inicio, fim)
                or self.dentro_periodo_tempos(despacho, inicio, fim)
            ):
                continue
            fim_lead = despacho or self._now()
            lead_seg = self.segundos_entre_datas(inicio_destaque, fim_lead) if inicio_destaque else None
            destaque_seg = self.segundos_entre_datas(inicio_destaque, finalizacao) if inicio_destaque and finalizacao else None
            fim_pallet = despacho or self._now()
            pallet_seg = self.segundos_entre_datas(finalizacao, fim_pallet) if finalizacao else None
            tarefa_id = tarefa.get("id")
            qtd_ops = contagens_ops.get(int(tarefa_id), 0) if tarefa_id is not None else 0
            tarefa_rows.append({
                "tarefa": tarefa.get("codigo_tarefa") or "",
                "material": tarefa.get("material") or "",
                "status": tarefa.get("status") or "Aguardando registro",
                "inicio": self.formatar_data_operacional(inicio_destaque),
                "finalizacao": self.formatar_data_operacional(finalizacao),
                "despacho": self.formatar_data_operacional(despacho),
                "lead_seg": lead_seg,
                "lead": self.formatar_segundos_operacional(lead_seg),
                "destaque_seg": destaque_seg,
                "tempo_destaque": self.formatar_segundos_operacional(destaque_seg),
                "pallet_seg": pallet_seg,
                "tempo_pallet": self.formatar_segundos_operacional(pallet_seg),
                "qtd_ops": qtd_ops,
            })
        tarefa_rows.sort(key=lambda item: item["lead_seg"] or 0, reverse=True)

        leads_fechados = [row["lead_seg"] for row in tarefa_rows if row["lead_seg"] is not None and row.get("despacho")]
        destaques_fechados = [row["destaque_seg"] for row in tarefa_rows if row["destaque_seg"] is not None and row.get("finalizacao")]
        pallets_fechados = [row["pallet_seg"] for row in tarefa_rows if row["pallet_seg"] is not None and row.get("despacho")]
        etapas_medias = [row["tempo_medio_seg"] for row in etapa_rows]
        criticas = sum(1 for row in op_rows if row.get("status_tempo") == self._status_final())
        indicadores = {
            "tarefas": len(tarefa_rows),
            "lead_medio": self.formatar_segundos_operacional(self.media_segundos(leads_fechados)),
            "destaque_medio": self.formatar_segundos_operacional(self.media_segundos(destaques_fechados)),
            "pallet_medio": self.formatar_segundos_operacional(self.media_segundos(pallets_fechados)),
            "tempo_medio_etapa": self.formatar_segundos_operacional(self.media_segundos(etapas_medias)),
            "ops": len(op_rows),
            "ops_criticas": criticas,
        }
        resultado = {
            "visao": categoria_setor.title() if categoria_setor else "Tarefas" if somente_tarefas else "Todos",
            "indicadores": indicadores,
            "etapas": etapa_rows,
            "tarefas": tarefa_rows,
            "ops": op_rows,
        }
        if somente_tarefas:
            resultado["etapas"] = []
            resultado["ops"] = []
            resultado["indicadores"]["ops"] = sum(row.get("qtd_ops", 0) for row in tarefa_rows)
            resultado["indicadores"]["ops_criticas"] = 0
        elif categoria_setor:
            duracoes_setor = [row["tempo_total_seg"] for row in op_rows]
            resultado["tarefas"] = []
            resultado["indicadores"] = {
                "tarefas": sum(row["etapas"] for row in etapa_rows),
                "lead_medio": self.formatar_segundos_operacional(self.media_segundos(duracoes_setor)),
                "destaque_medio": self.formatar_segundos_operacional(sum(duracoes_setor)),
                "pallet_medio": self.formatar_segundos_operacional(max(duracoes_setor) if duracoes_setor else None),
                "tempo_medio_etapa": self.formatar_segundos_operacional(self.media_segundos(duracoes_setor)),
                "ops": len(op_rows),
                "ops_criticas": sum(1 for row in op_rows if row.get("tempo_aberto_seg") is not None),
            }
        return resultado

    def calcular_dashboard_movimentacoes(self, dias=30):
        """Consolida dados rastreados para os gráficos operacionais do MES."""

        dias = max(7, min(90, int(dias or 30)))
        fim = self._now()
        inicio = (fim - timedelta(days=dias - 1)).replace(hour=0, minute=0, second=0, microsecond=0)
        historico = self.db.obter_historico_completo(
            periodo_inicio=inicio,
            periodo_fim=fim,
            tipo=MOVEMENT_TYPE,
        )
        movimentos = []
        for row in historico:
            op = str(row.get("op") or "").strip()
            data_hora = self.parse_data_operacional(row.get("data_hora"))
            if not op or op.upper().startswith("T") or not data_hora:
                continue
            movimentos.append({**row, "op": op, "_data_dt": data_hora})
        movimentos.sort(key=lambda item: (item["op"], item["_data_dt"], item.get("id") or 0))

        por_op = {}
        for movimento in movimentos:
            por_op.setdefault(movimento["op"], []).append(movimento)

        latest = {}
        try:
            atuais = self.db.get_current_ops(
                maquinas_dobra=self.maquinas_dobra,
                maquinas_usinagem=self.maquinas_usinagem,
                maquinas_serra=self.maquinas_serra,
            )
        except (AttributeError, TypeError):
            atuais = []
        for item in atuais or []:
            op = str(item.get("op") or "").strip()
            if op:
                latest[op] = dict(item)
        if not latest:
            for movimento in movimentos:
                latest[movimento["op"]] = movimento

        pecas_setor = {}
        for item in latest.values():
            setor = str(item.get("setor") or "Sem setor").strip() or "Sem setor"
            quantidade = item.get("quantidade")
            try:
                quantidade = int(quantidade) if quantidade is not None else 1
            except (TypeError, ValueError):
                quantidade = 1
            pecas_setor[setor] = pecas_setor.get(setor, 0) + max(0, quantidade)

        movimentos_dia = {}
        cursor = inicio.date()
        while cursor <= fim.date():
            movimentos_dia[cursor] = 0
            cursor += timedelta(days=1)
        for movimento in movimentos:
            dia = movimento["_data_dt"].date()
            if dia in movimentos_dia:
                movimentos_dia[dia] += 1

        tempos_setor = {}
        transicoes = {}
        for eventos in por_op.values():
            for index, evento in enumerate(eventos):
                setor = str(evento.get("setor") or "").strip()
                proximo = eventos[index + 1] if index + 1 < len(eventos) else None
                fim_etapa = min(proximo["_data_dt"] if proximo else fim, fim)
                segundos = max(0, int((fim_etapa - evento["_data_dt"]).total_seconds()))
                if setor:
                    stats = tempos_setor.setdefault(setor, {"total": 0, "passagens": 0, "maior": 0})
                    stats["total"] += segundos
                    stats["passagens"] += 1
                    stats["maior"] = max(stats["maior"], segundos)
                if not proximo:
                    continue
                destino = str(proximo.get("setor") or "").strip()
                if not setor or not destino or setor.casefold() == destino.casefold():
                    continue
                fluxo = f"{setor} → {destino}"
                stats = transicoes.setdefault(fluxo, {"total": 0, "ocorrencias": 0, "maior": 0})
                stats["total"] += segundos
                stats["ocorrencias"] += 1
                stats["maior"] = max(stats["maior"], segundos)

        tempo_rows = []
        for setor, stats in tempos_setor.items():
            media = stats["total"] / stats["passagens"] if stats["passagens"] else 0
            tempo_rows.append({
                "setor": setor,
                "passagens": stats["passagens"],
                "media_segundos": media,
                "media_horas": media / 3600,
                "media": self.formatar_segundos_operacional(media),
                "maior_segundos": stats["maior"],
            })
        tempo_rows.sort(key=lambda row: row["media_segundos"], reverse=True)

        transicao_rows = []
        for fluxo, stats in transicoes.items():
            media = stats["total"] / stats["ocorrencias"] if stats["ocorrencias"] else 0
            transicao_rows.append({
                "fluxo": fluxo,
                "ocorrencias": stats["ocorrencias"],
                "media_segundos": media,
                "media_horas": media / 3600,
                "media": self.formatar_segundos_operacional(media),
                "maior_segundos": stats["maior"],
            })
        transicao_rows.sort(key=lambda row: row["media_segundos"], reverse=True)

        gargalo = tempo_rows[0] if tempo_rows else None
        dias_rows = [
            {"data": dia, "label": dia.strftime("%d/%m"), "quantidade": quantidade}
            for dia, quantidade in movimentos_dia.items()
        ]
        setor_rows = [
            {"setor": setor, "quantidade": quantidade}
            for setor, quantidade in sorted(pecas_setor.items(), key=lambda item: item[1], reverse=True)
        ]
        return {
            "periodo_dias": dias,
            "kpis": {
                "ops_fluxo": len(latest),
                "pecas_fluxo": sum(pecas_setor.values()),
                "movimentos_7d": sum(row["quantidade"] for row in dias_rows[-7:]),
                "gargalo_setor": gargalo["setor"] if gargalo else "-",
                "gargalo_tempo": gargalo["media"] if gargalo else "Sem dados",
            },
            "movimentos_dia": dias_rows,
            "pecas_setor": setor_rows,
            "tempos_setor": tempo_rows,
            "transicoes": transicao_rows,
        }

    def texto_linha_exportacao_tempos(self, row):
        return " ".join(str(valor or "") for valor in row.values()).upper()

    def linha_passa_filtros_tempos(self, row, filtros, campos_setor=None, campo_status=None):
        texto = (filtros.get("texto") or "").upper()
        setor = (filtros.get("setor") or "").upper()
        status = filtros.get("status") or "Todos"
        if texto and texto not in self.texto_linha_exportacao_tempos(row):
            return False
        if setor and campos_setor:
            if not any(setor in str(row.get(campo) or "").upper() for campo in campos_setor):
                return False
        if campo_status and status != "Todos" and row.get(campo_status) != status:
            return False
        return True

    def montar_linhas_exportacao_tempos_mes(self, resultado, filtros):
        linhas = []
        if filtros.get("resumo"):
            indicadores = resultado.get("indicadores", {})
            linhas.append({
                "tipo": "Resumo",
                "grupo": "Período atual",
                "item": "Indicadores",
                "descricao": "Tempos MES",
                "status": "",
                "quantidade": indicadores.get("tarefas", ""),
                "tempo_medio": indicadores.get("tempo_medio_etapa", ""),
                "maior_tempo": "",
                "tempo_total": "",
                "tempo_aberto": "",
                "inicio": "",
                "fim": "",
                "observacao": (
                    f"Lead médio: {indicadores.get('lead_medio', '')} | "
                    f"Destaque médio: {indicadores.get('destaque_medio', '')} | "
                    f"Pallet médio: {indicadores.get('pallet_medio', '')} | "
                    f"OPs: {indicadores.get('ops', '')} | Críticas: {indicadores.get('ops_criticas', '')}"
                ),
            })

        if filtros.get("etapas"):
            for row in resultado.get("etapas", []):
                if not self.linha_passa_filtros_tempos(row, filtros, campos_setor=("setor",)):
                    continue
                linhas.append({
                    "tipo": "Permanência por setor",
                    "grupo": row.get("setor", ""),
                    "item": row.get("setor", ""),
                    "descricao": "Setor/Máquina",
                    "status": "",
                    "quantidade": row.get("etapas", ""),
                    "tempo_medio": row.get("tempo_medio", ""),
                    "maior_tempo": row.get("maior_tempo", ""),
                    "tempo_total": row.get("tempo_total", ""),
                    "tempo_aberto": "",
                    "inicio": "",
                    "fim": "",
                    "observacao": f"OPs ainda no setor: {row.get('abertas', 0)}",
                })

        if filtros.get("tarefas"):
            for row in resultado.get("tarefas", []):
                if not self.linha_passa_filtros_tempos(row, filtros):
                    continue
                linhas.append({
                    "tipo": "Fluxo da tarefa",
                    "grupo": row.get("tarefa", ""),
                    "item": row.get("tarefa", ""),
                    "descricao": row.get("material", ""),
                    "status": row.get("status", ""),
                    "quantidade": row.get("qtd_ops", ""),
                    "tempo_medio": row.get("tempo_destaque", ""),
                    "maior_tempo": row.get("tempo_pallet", ""),
                    "tempo_total": row.get("lead", ""),
                    "tempo_aberto": "",
                    "inicio": row.get("inicio", ""),
                    "fim": row.get("despacho", ""),
                    "finalizacao": row.get("finalizacao", ""),
                    "tempo_destaque": row.get("tempo_destaque", ""),
                    "tempo_pallet": row.get("tempo_pallet", ""),
                    "observacao": "Fluxo destaque -> finalizacao -> despacho",
                })

        if filtros.get("ops"):
            for row in resultado.get("ops", []):
                if not self.linha_passa_filtros_tempos(row, filtros, campos_setor=("setor_atual",), campo_status="status_tempo"):
                    continue
                linhas.append({
                    "tipo": "Tempo por OP",
                    "grupo": row.get("tarefa", ""),
                    "item": row.get("op", ""),
                    "descricao": row.get("peca", ""),
                    "status": row.get("status_tempo", ""),
                    "quantidade": row.get("movimentacoes", ""),
                    "tempo_medio": "",
                    "maior_tempo": "",
                    "tempo_total": row.get("tempo_total", ""),
                    "tempo_aberto": row.get("tempo_aberto", ""),
                    "inicio": "",
                    "fim": "",
                    "observacao": f"Setor atual: {row.get('setor_atual', '')}",
                })
        return linhas

    def buscar_movimentacoes_periodo(self, inicio, fim):
        return self.db.buscar_movimentacoes_periodo(inicio, fim)

    def _now(self):
        return self._now_func()

    def _status_final(self):
        if not self.status_limits:
            return ""
        for limite, status in reversed(self.status_limits):
            if limite is None:
                return status
        return self.status_limits[-1][1]
