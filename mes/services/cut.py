"""Fila automática e apontamento de Corte baseado no catálogo SIGMANEST."""

from dataclasses import dataclass
from datetime import datetime
import json
import logging
import re
from typing import Optional

from mes.domain.manufacturing_rules import ManufacturingRules

DEFAULT_CUT_QUEUE_START_DATE = "2026-08-03"


CUT_MACHINE_MAP = {
    "AMADA_ENSIS": "Laser Ensis 3015",
    "MESSER_XPR_300": "Plasma TerraBlade 4",
}
CUT_MACHINE_REVERSE = {value: key for key, value in CUT_MACHINE_MAP.items()}


# Estados operacionais de um plano dentro da tarefa. "Aguardando corte" e
# "disponível para Destaque" são situações diferentes e nunca se confundem:
# a primeira é trabalho pendente do Corte, a segunda é trabalho já cortado que
# o Destaque pode puxar.
PLAN_STATE_WAITING_CUT = "AGUARDANDO CORTE"
PLAN_STATE_CUTTING = "EM CORTE"
PLAN_STATE_HIGHLIGHT_READY = "DISPONÍVEL PARA DESTAQUE"
PLAN_STATE_DONE = "FINALIZADO"

# Estado do Destaque que encerra o plano (mesmo vocabulário de
# ``Database.listar_fila_destaque``).
HIGHLIGHT_DONE_STATE = "fim"


@dataclass
class CutResult:
    ok: bool
    message: str
    code: str = ""
    data: Optional[dict] = None


class CutService:
    """Mantém a fila virtual até o operador iniciar fisicamente o corte."""

    def __init__(self, db, operador, cutoff_date=DEFAULT_CUT_QUEUE_START_DATE, now_func=None):
        self.db = db
        self.operador = operador
        self.cutoff_date = cutoff_date
        self._now = now_func or datetime.now
        # Caches de leitura por instância: o agrupamento da fila é chamado
        # várias vezes no mesmo comando e nenhuma dessas projeções muda no
        # meio de uma requisição. Evita N+1 sem inventar estado persistido.
        self._catalog_ops_cache = {}
        self._highlight_states_cache = None

    @staticmethod
    def machine_display(machine_sigmanest):
        normalized = str(machine_sigmanest or "").strip().upper()
        return CUT_MACHINE_MAP.get(normalized, str(machine_sigmanest or "").strip())

    @staticmethod
    def machine_sigmanest(machine_display):
        return CUT_MACHINE_REVERSE.get(str(machine_display or "").strip())

    def listar_fila(self, maquina=None):
        machine_sigmanest = self.machine_sigmanest(maquina) if maquina else None
        rows = self.db.listar_fila_corte(
            self.cutoff_date,
            maquina_sigmanest=machine_sigmanest,
            agora=self._now(),
        )
        return self._group_rows(rows)

    def iniciar(self, plano_hash, maquina):
        requested = str(plano_hash).strip()
        eligible = next(
            (
                row for row in self.listar_fila(maquina)
                if requested in row.get("plano_hashes", [])
                and row.get("status") == "Aguardando"
            ),
            None,
        )
        if not eligible:
            return CutResult(
                False,
                "O plano não está mais aguardando nesta máquina. Atualize a fila.",
                code="plano_indisponivel",
            )
        # A chapa escolhida pelo operador é respeitada quando ainda aguarda;
        # caso contrário a fila segue sua própria ordem operacional. O comando
        # continua sendo um só — nenhuma ação nova foi criada.
        aguardando = eligible["plano_hashes_aguardando"]
        next_hash = requested if requested in aguardando else aguardando[0]
        started = self.db.iniciar_apontamento_corte(
            next_hash,
            maquina,
            self.operador,
            self.cutoff_date,
            data_inicio=self._now(),
        )
        if not started:
            return CutResult(
                False,
                "O corte já foi iniciado ou concluído por outro operador.",
                code="estado_alterado",
            )
        row = next(
            (
                item for item in self.listar_fila(maquina)
                if item.get("codigo_tarefa") == eligible.get("codigo_tarefa")
            ),
            self._group_rows([started])[0],
        )
        self._record_event("corte_iniciado", row, f"Corte iniciado em {maquina}.")
        return CutResult(True, "Nesting iniciado.", data=row)

    def estado_recurso(self, maquina):
        loader = getattr(self.db, "buscar_estado_recurso_atual", None)
        if not callable(loader):
            return None
        state = loader(str(maquina or "").strip())
        return dict(state) if state else None

    def parar(self, maquina, *, motivo_codigo, comentario=None):
        """Registra parada manual do recurso de Corte sem encerrar o nesting ativo."""

        machine = str(maquina or "").strip()
        active = next(
            (row for row in self.listar_fila(machine) if row.get("status") == "Em processo"),
            None,
        )
        finder = getattr(self.db, "buscar_status_recurso", None)
        status = finder(str(motivo_codigo or "").strip()) if callable(finder) else None
        if (
            not status
            or not status.get("habilitado")
            or status.get("oculto")
            or status.get("setup")
            or status.get("retrabalho")
            or status.get("grupo_codigo") == "0001"
        ):
            return CutResult(False, "Selecione um motivo de parada válido.", code="motivo_invalido")
        if status.get("requer_comentario") and not str(comentario or "").strip():
            return CutResult(False, "O motivo selecionado exige comentário.", code="comentario_obrigatorio")
        current = self.estado_recurso(machine)
        if current and current.get("categoria") == "parada":
            return CutResult(False, "O recurso já está parado.", code="ja_parado", data=current)
        transition = getattr(self.db, "transicionar_estado_recurso", None)
        if not callable(transition):
            return CutResult(False, "O estado físico do recurso não está disponível.", code="estado_indisponivel")
        reason = " - ".join(
            value for value in (str(status.get("codigo") or "").strip(), str(status.get("nome") or "").strip()) if value
        )
        active_id = (
            next(iter(active.get("apontamento_ids_em_processo") or []), active.get("id"))
            if active
            else None
        )
        changed = transition(
            machine,
            "parada",
            tipo_setor="Corte",
            operador=self.operador,
            codigo_status_recurso=status.get("codigo"),
            motivo=reason,
            causa_raiz=status.get("causa_raiz"),
            comentario=str(comentario or "").strip() or None,
            origem="corte_parada_manual",
            referencia_origem=f"nesting:{active_id}" if active_id is not None else None,
            # A origem é manual, mas a classificação é a do motivo canônico.
            # Ex.: 0009 (pausa para café) pertence ao grupo 0002 e permanece
            # parada programada; "manual" não pode apagar essa regra.
            planejado=status.get("planejado"),
            automatico=False,
            tipo_interrupcao="manual",
            data_hora=self._now(),
        )
        if not changed:
            return CutResult(False, "Não foi possível registrar a parada do Corte.", code="estado_alterado")
        payload = dict(active or {"maquina": machine, "status": "Sem nesting ativo"})
        payload["estado_recurso"] = dict(changed)
        self._record_event("corte_parado", payload, f"Parada de Corte registrada: {reason}.")
        return CutResult(True, "Parada registrada.", data=payload)

    def retomar(self, maquina):
        """Retoma o recurso após uma parada manual, com ou sem nesting ativo.

        Simétrico de ``parar``: a parada pode ser registrada sem nenhum
        nesting em processo, então a retomada também não pode exigir um.
        Sem nesting ativo o recurso volta para ``fila`` (sem demanda).
        """

        machine = str(maquina or "").strip()
        active = next(
            (row for row in self.listar_fila(machine) if row.get("status") == "Em processo"),
            None,
        )
        current = self.estado_recurso(machine)
        if not current or current.get("categoria") not in {"parada", "fora_turno"}:
            return CutResult(False, "O recurso não está parado.", code="nao_parado", data=current)
        if current.get("categoria") == "fora_turno" and not (
            current.get("automatico")
            and current.get("tipo_interrupcao") == "fim_turno"
        ):
            return CutResult(
                False,
                "O recurso está fora de turno sem interrupção automática retomável.",
                code="fora_turno_nao_retomavel",
                data=current,
            )
        transition = getattr(self.db, "transicionar_estado_recurso", None)
        if not callable(transition):
            return CutResult(False, "O estado físico do recurso não está disponível.", code="estado_indisponivel")
        active_id = (
            next(iter(active.get("apontamento_ids_em_processo") or []), active.get("id"))
            if active
            else None
        )
        nesting = (active.get("nesting_atual") or active.get("sequencia_nesting") or "") if active else ""
        changed = transition(
            machine,
            "producao" if active else "fila",
            tipo_setor="Corte",
            operador=self.operador,
            motivo=f"Nesting {nesting}".strip() if active else "Retomada sem nesting ativo",
            origem="corte_nesting" if active else "corte_retomada_sem_nesting",
            referencia_origem=f"nesting:{active_id}" if active_id is not None else None,
            planejado=None,
            automatico=False,
            data_hora=self._now(),
        )
        if not changed:
            return CutResult(False, "Não foi possível retomar o Corte.", code="estado_alterado")
        payload = dict(active or {"maquina": machine, "status": "Sem nesting ativo"})
        payload["estado_recurso"] = dict(changed)
        self._record_event("corte_retomado", payload, f"Corte retomado em {machine}.")
        return CutResult(True, "Corte retomado.", data=payload)

    def finalizar(self, apontamento_id):
        eligible = next(
            (
                row for row in self.listar_fila()
                if int(apontamento_id) in row.get("apontamento_ids", [])
                and row.get("status") == "Em processo"
            ),
            None,
        )
        if not eligible:
            return CutResult(
                False,
                "O plano não está mais em processo. Atualize a fila.",
                code="estado_alterado",
            )
        active_id = int(apontamento_id)
        next_hashes = eligible.get("plano_hashes_aguardando", [])
        advanced = None
        if next_hashes:
            advanced = self.db.avancar_nesting_corte(
                active_id,
                next_hashes[0],
                self.operador,
                self.cutoff_date,
                momento=self._now(),
            )
            finished = advanced.get("finalizado") if advanced else None
        else:
            finished = self.db.finalizar_apontamento_corte(
                active_id,
                self.operador,
                data_fim=self._now(),
            )
        if not finished:
            return CutResult(
                False,
                "O plano não está mais em processo. Atualize a fila.",
                code="estado_alterado",
            )
        refreshed = next(
            (
                item for item in self.listar_fila()
                if item.get("codigo_tarefa") == eligible.get("codigo_tarefa")
                and item.get("maquina") == eligible.get("maquina")
            ),
            None,
        )
        if refreshed is None:
            row = dict(eligible)
            row.update({
                "status": "Finalizado",
                "nestings_concluidos": row.get("nesting_count", 1),
                "nestings_em_processo": 0,
                "nestings_aguardando": 0,
                "operador_fim": finished.get("operador_fim"),
                "data_fim": finished.get("data_fim"),
                "tempo_real_segundos": finished.get("tempo_real_segundos"),
            })
            message = "Todos os nestings foram concluídos. Tarefa finalizada."
        else:
            row = refreshed
            completed = int(row.get("nestings_concluidos") or 0)
            total = int(row.get("nesting_count") or 1)
            message = (
                f"Nesting {completed}/{total} concluído. Próximo nesting iniciado."
            )
        event_type = "corte_finalizado" if refreshed is None else "corte_nesting_concluido"
        self._record_event(event_type, row, message)
        return CutResult(True, message, data=row)

    def listar_consulta(self, maquina=None, status="Todos", search=None):
        current = self.listar_fila(maquina=maquina)
        completed = self.db.listar_apontamentos_corte(
            maquina=maquina,
            status="Finalizado",
            search=search,
            agora=self._now(),
        )
        current_keys = {
            (row.get("codigo_tarefa"), row.get("maquina")) for row in current
        }
        completed_groups = [
            row for row in self._group_rows(completed)
            if (row.get("codigo_tarefa"), row.get("maquina")) not in current_keys
        ]
        rows = current + completed_groups
        if status and status != "Todos":
            rows = [row for row in rows if row.get("status") == status]
        if search:
            needle = str(search).strip().casefold()
            rows = [
                row for row in rows
                if any(
                    needle in str(row.get(key) or "").casefold()
                    for key in ("codigo_tarefa", "programa", "material", "maquina")
                )
            ]
        rows.sort(key=lambda item: (
            item.get("codigo_tarefa") or "",
            item.get("programa") or "",
        ))
        if status == "Finalizado":
            # Histórico é uma timeline de execução: a conclusão mais recente
            # vem primeiro. Ordenar pela data do plano fazia tarefas antigas
            # aparecerem acima de apontamentos recém-finalizados.
            def execution_time(item):
                value = item.get("data_fim") or item.get("data_inicio")
                if isinstance(value, datetime):
                    return value
                try:
                    return datetime.fromisoformat(str(value or ""))
                except ValueError:
                    return datetime.min

            rows.sort(key=execution_time, reverse=True)
        else:
            rows.sort(
                key=lambda item: item.get("data_programa") or datetime.min.date(),
                reverse=True,
            )
        rows.sort(
            key=lambda item: {
                "Em processo": 0,
                "Aguardando": 1,
                "Finalizado": 2,
            }.get(item.get("status"), 3)
        )
        return rows

    def listar_tempos_nesting(self, inicio=None, fim=None, maquina=None, search=None):
        """Retorna cada nesting como execução temporal independente.

        A tarefa continua agrupada na fila operacional, mas relatórios e gestores
        recebem uma linha por nesting para não perder duração, desvio e operador.
        """

        loader = getattr(self.db, "listar_tempos_nesting_corte", None)
        if callable(loader):
            return list(loader(inicio=inicio, fim=fim, maquina=maquina, search=search) or [])

        rows = self.db.listar_apontamentos_corte(
            inicio=inicio, fim=fim, maquina=maquina, search=search
        )
        result = []
        for raw in rows:
            row = dict(raw)
            planned = float(row.get("tempo_previsto_segundos") or 0) or None
            real = (
                float(row.get("tempo_real_segundos") or 0)
                if row.get("tempo_real_segundos") is not None
                else None
            )
            deviation = real - planned if real is not None and planned is not None else None
            period_start = self._as_datetime(inicio) if inicio else None
            period_end = self._as_datetime(fim, end_of_day=False) if fim else None
            execution_start = self._as_datetime(row.get("data_inicio"))
            execution_end = self._as_datetime(row.get("data_fim")) or self._now()
            clipped_start = max(execution_start, period_start) if execution_start and period_start else execution_start
            clipped_end = min(execution_end, period_end) if execution_end and period_end else execution_end
            real_period = (
                max(0.0, (clipped_end - clipped_start).total_seconds())
                if clipped_start and clipped_end and clipped_end >= clipped_start
                else 0.0
            )
            result.append({
                "apontamento_id": row.get("id"),
                "plano_hash": row.get("plano_hash"),
                "tarefa": row.get("codigo_tarefa"),
                "programa": row.get("programa"),
                "nesting": row.get("sequencia_nesting"),
                "maquina": row.get("maquina"),
                "material": row.get("material"),
                "espessura": row.get("espessura"),
                "inicio": row.get("data_inicio"),
                "fim": row.get("data_fim"),
                "previsto_segundos": planned,
                "real_segundos": real,
                "real_periodo_segundos": real_period,
                "desvio_segundos": deviation,
                "desvio_percentual": (deviation / planned * 100.0) if deviation is not None and planned else None,
                "status": row.get("status"),
                "operador_inicio": row.get("operador_inicio"),
                "operador_fim": row.get("operador_fim"),
            })
        return result

    def calcular_dashboard_mes(self, inicio, fim, maquina=None):
        """Consolida somente dados que já existem no catálogo e nos apontamentos."""

        start = self._as_datetime(inicio)
        end = self._as_datetime(fim, end_of_day=True)
        if start is None or end is None or end < start:
            raise ValueError("Período inválido para o painel MES de Corte.")

        nesting_rows = self.listar_tempos_nesting(start, end, maquina=maquina)
        all_rows = self.listar_consulta(maquina=maquina, status="Todos")
        period_rows = []
        for row in all_rows:
            reference = self._dashboard_reference_date(row)
            if reference is not None and start <= reference <= end:
                period_rows.append(row)

        machine_names = [maquina] if maquina else list(CUT_MACHINE_REVERSE)
        machine_summaries = {}
        for machine_name in machine_names:
            machine_rows = [
                row for row in all_rows if row.get("maquina") == machine_name
            ]
            active = next(
                (row for row in machine_rows if row.get("status") == "Em processo"),
                None,
            )
            waiting = next(
                (row for row in machine_rows if row.get("status") == "Aguardando"),
                None,
            )
            current = active or waiting
            machine_summaries[machine_name] = {
                "maquina": machine_name,
                "status": (
                    "Em processo" if active
                    else "Aguardando" if waiting
                    else "Sem fila ativa"
                ),
                "tarefa": current.get("codigo_tarefa") if current else None,
                "plano": current.get("programa_atual") if current else None,
                "nesting_atual": current.get("nesting_atual") if active else None,
                "nestings_concluidos": int(current.get("nestings_concluidos") or 0) if current else 0,
                "nesting_count": int(current.get("nesting_count") or 0) if current else 0,
                "tempo_previsto_segundos": float(current.get("tempo_previsto_segundos") or 0) if current else 0.0,
                "tempo_real_segundos": float(current.get("tempo_real_segundos") or 0) if current else 0.0,
                "nestings_na_fila": sum(
                    int(row.get("nestings_aguardando") or 0)
                    for row in machine_rows
                ),
            }

        return {
            "periodo": {"inicio": start, "fim": end},
            "maquina": maquina,
            "indicadores": {
                "tarefas": len(period_rows),
                "nestings_concluidos": sum(
                    int(row.get("nestings_concluidos") or 0)
                    for row in period_rows
                ),
                "tempo_previsto_segundos": sum(
                    float(row.get("tempo_previsto_segundos") or 0)
                    for row in period_rows
                ),
                "tempo_real_segundos": sum(
                    float(row.get("real_periodo_segundos", row.get("real_segundos")) or 0)
                    for row in nesting_rows
                ),
            },
            "maquinas": machine_summaries,
            "atividades": period_rows,
            "nestings": nesting_rows,
        }

    @staticmethod
    def _dashboard_reference_date(row):
        status = row.get("status")
        if status == "Finalizado":
            value = row.get("data_fim") or row.get("data_inicio")
        elif status == "Em processo":
            value = row.get("data_inicio") or row.get("data_programa")
        else:
            value = row.get("data_programa")
        return CutService._as_datetime(value)

    @staticmethod
    def _as_datetime(value, end_of_day=False):
        if value is None:
            return None
        if isinstance(value, datetime):
            if end_of_day and value.time() == datetime.min.time():
                return value.replace(hour=23, minute=59, second=59)
            return value
        if hasattr(value, "year") and hasattr(value, "month") and hasattr(value, "day"):
            return datetime(
                value.year,
                value.month,
                value.day,
                23 if end_of_day else 0,
                59 if end_of_day else 0,
                59 if end_of_day else 0,
            )
        try:
            parsed = datetime.fromisoformat(str(value).strip())
        except (TypeError, ValueError):
            return None
        if end_of_day and parsed.time() == datetime.min.time():
            return parsed.replace(hour=23, minute=59, second=59)
        return parsed

    @classmethod
    def _decorate(cls, row):
        item = dict(row or {})
        if not item.get("maquina"):
            item["maquina"] = cls.machine_display(item.get("maquina_sigmanest"))
        return item

    # ------------------------------------------------------------------
    # Hierarquia operacional: TAREFA -> PLANO/NESTING -> OP -> PRODUTO
    # ------------------------------------------------------------------
    def _catalog_ops(self, task_code):
        """Linhas de peça da tarefa já projetadas localmente (com produto).

        Uma leitura por tarefa e por instância do serviço: a tela de Corte usa
        somente a projeção local, sem consultar OP por OP nem voltar à origem
        corporativa para montar a hierarquia.
        """

        code = str(task_code or "").strip()
        if not code:
            return []
        if code not in self._catalog_ops_cache:
            loader = getattr(self.db, "listar_ops_catalogo_tarefa", None)
            rows = []
            if callable(loader):
                try:
                    rows = [dict(row) for row in (loader(code) or ())]
                except Exception:  # pragma: no cover - catálogo indisponível
                    logging.exception("Falha ao ler as OPs do catálogo da tarefa %s", code)
                    rows = []
            self._catalog_ops_cache[code] = rows
        return self._catalog_ops_cache[code]

    def _highlight_states(self):
        """Estado de Destaque por plano, vindo do read model canônico.

        A regra de disponibilidade para o Destaque **não** é reescrita aqui:
        ``listar_fila_destaque`` continua sendo a única fonte (máquina que
        libera, chapa cortada, plano ainda não destacado). O Corte apenas lê o
        estado para rotular o plano corretamente.
        """

        if self._highlight_states_cache is None:
            loader = getattr(self.db, "listar_fila_destaque", None)
            estados = {}
            if callable(loader):
                try:
                    for grupo in loader(limite=10000) or ():
                        for plano in grupo.get("planos") or ():
                            chave = str(plano.get("plano_hash") or "").strip()
                            if chave:
                                estados[chave] = str(
                                    plano.get("estado_destaque") or "aguardando"
                                ).strip().lower()
                except Exception:  # pragma: no cover - fila do Destaque indisponível
                    logging.exception("Falha ao ler a fila do Destaque para a hierarquia de Corte")
                    estados = {}
            self._highlight_states_cache = estados
        return self._highlight_states_cache

    @staticmethod
    def _op_entry(row):
        """Projeção mínima de uma OP dentro do plano, com o produto local."""

        return {
            "codigo_op": str(row.get("codigo_op") or "").strip(),
            "id_peca": row.get("id_peca") or None,
            # ``produto_codigo`` vem do catálogo canônico de OPs; ``id_peca`` é
            # o código observado no planejamento e serve de diagnóstico quando
            # a OP ainda não foi recebida.
            "produto_codigo": row.get("produto_codigo") or row.get("id_peca") or None,
            "produto_descricao": row.get("produto_descricao") or None,
            "quantidade": row.get("quantidade"),
            "quantidade_op": row.get("quantidade_op"),
            "setor_destino": row.get("setor_destino") or None,
        }

    @classmethod
    def _dedupe_ops(cls, rows):
        entries = {}
        for row in rows:
            entry = cls._op_entry(row)
            if not entry["codigo_op"]:
                continue
            atual = entries.get(entry["codigo_op"])
            if atual is None:
                entries[entry["codigo_op"]] = entry
                continue
            # A mesma OP pode ter mais de uma peça no plano; preserva-se a
            # maior quantidade observada, como a própria projeção faz.
            atual["quantidade"] = max(
                int(atual.get("quantidade") or 0), int(entry.get("quantidade") or 0)
            )
        return sorted(entries.values(), key=lambda item: item["codigo_op"])

    def _ops_por_plano(self, task_code, programs):
        """Distribui as OPs da tarefa entre os programas em que foram aninhadas.

        Nada é adivinhado: linhas sem programa (projetadas antes desta wave)
        só são atribuídas quando a tarefa tem um único plano — caso em que a
        atribuição é a própria definição de tarefa. Com vários planos elas
        ficam explicitamente fora, em ``ops_sem_plano``.
        """

        catalogo = self._catalog_ops(task_code)
        indice = {str(programa).strip().casefold(): programa for programa in programs}
        por_plano = {programa: [] for programa in programs}
        sem_plano = []
        for row in catalogo:
            programa = indice.get(str(row.get("programa") or "").strip().casefold())
            if programa is None:
                sem_plano.append(row)
            else:
                por_plano[programa].append(row)
        if sem_plano and len(programs) == 1:
            por_plano[programs[0]].extend(sem_plano)
            sem_plano = []
        return (
            {programa: self._dedupe_ops(linhas) for programa, linhas in por_plano.items()},
            self._dedupe_ops(sem_plano),
        )

    @classmethod
    def _plan_state(cls, *, waiting, active, completed, machine_sigmanest, highlight_states):
        """Estado operacional do plano, sem confundir Corte com Destaque."""

        if active:
            return PLAN_STATE_CUTTING
        if waiting:
            # Plano com chapa já cortada e chapa pendente continua sendo
            # trabalho do Corte — jamais "aguardando destaque".
            return PLAN_STATE_CUTTING if completed else PLAN_STATE_WAITING_CUT
        if not ManufacturingRules.cut_releases_highlight(machine_sigmanest):
            return PLAN_STATE_DONE
        pendente = any(
            highlight_states.get(str(item.get("plano_hash") or "").strip(), "aguardando")
            != HIGHLIGHT_DONE_STATE
            for item in completed
        )
        return PLAN_STATE_HIGHLIGHT_READY if pendente else PLAN_STATE_DONE

    def _build_plans(self, items, machine_sigmanest, task_code, programs):
        """Planos da tarefa, cada um com suas chapas reais e suas OPs."""

        ops_por_plano, ops_sem_plano = self._ops_por_plano(task_code, programs)
        precisa_destaque = any(item.get("status") == "Finalizado" for item in items)
        highlight_states = self._highlight_states() if precisa_destaque else {}
        planos = []
        for ordem, programa in enumerate(programs, start=1):
            chapas = [
                item for item in items
                if str(item.get("programa") or "").strip() == programa
            ]
            waiting = [item for item in chapas if item.get("status") == "Aguardando"]
            active = [item for item in chapas if item.get("status") == "Em processo"]
            completed = [item for item in chapas if item.get("status") == "Finalizado"]
            disponiveis = [
                item for item in completed
                if highlight_states.get(str(item.get("plano_hash") or "").strip(), "aguardando")
                != HIGHLIGHT_DONE_STATE
            ] if ManufacturingRules.cut_releases_highlight(machine_sigmanest) else []
            representativa = (active or waiting or completed)[0]
            planos.append({
                "programa": programa,
                "ordem": ordem,
                "estado": self._plan_state(
                    waiting=waiting,
                    active=active,
                    completed=completed,
                    machine_sigmanest=machine_sigmanest,
                    highlight_states=highlight_states,
                ),
                # Cada linha projetada É uma chapa física do programa
                # (programa + chapa + repetição), direto do SigmaNEST. Nada
                # aqui presume "1 nesting = 1 chapa".
                "chapas_total": len(chapas),
                "chapas_cortadas": len(completed),
                "chapas_em_corte": len(active),
                "chapas_aguardando": len(waiting),
                "chapas_disponiveis_destaque": len(disponiveis),
                "libera_destaque": ManufacturingRules.cut_releases_highlight(machine_sigmanest),
                "repeticoes": sorted({
                    int(item["sigmanest_repeat_id"])
                    for item in chapas
                    if item.get("sigmanest_repeat_id") is not None
                }),
                "nome_chapa": ", ".join(dict.fromkeys(
                    str(item.get("nome_chapa") or "").strip()
                    for item in chapas
                    if str(item.get("nome_chapa") or "").strip()
                )) or None,
                "quantidade_processo": sum(
                    int(item.get("quantidade_processo") or 0) for item in chapas
                ),
                "tempo_previsto_segundos": sum(
                    float(item.get("tempo_previsto_segundos") or 0) for item in chapas
                ),
                "tempo_real_segundos": sum(
                    max(0.0, float(item.get("tempo_real_segundos") or 0.0))
                    for item in chapas
                ),
                "plano_hash": representativa.get("plano_hash"),
                "plano_hashes": [item.get("plano_hash") for item in chapas],
                "plano_hashes_aguardando": [item.get("plano_hash") for item in waiting],
                "apontamento_ids_em_processo": [
                    item.get("id") for item in active if item.get("id") is not None
                ],
                "ops": ops_por_plano.get(programa, []),
                "chapas": [self._nesting_entry(item) for item in chapas],
            })
        return planos, ops_sem_plano

    @staticmethod
    def _nesting_entry(item):
        return {
            "apontamento_id": item.get("id"),
            "plano_hash": item.get("plano_hash"),
            "sequencia": item.get("sequencia_nesting"),
            "programa": item.get("programa"),
            "nome_chapa": item.get("nome_chapa"),
            "repeticao": item.get("sigmanest_repeat_id"),
            "status": item.get("status"),
            "tempo_previsto_segundos": item.get("tempo_previsto_segundos"),
            "tempo_real_segundos": item.get("tempo_real_segundos"),
            "quantidade_processo": item.get("quantidade_processo"),
            "maquina": item.get("maquina"),
            "operador_inicio": item.get("operador_inicio"),
            "operador_fim": item.get("operador_fim"),
            "data_programa": item.get("data_programa"),
            "data_inicio": item.get("data_inicio"),
            "data_fim": item.get("data_fim"),
        }

    def _group_rows(self, rows, separate_sessions=False):
        groups = {}
        for raw in rows or []:
            item = self._decorate(raw)
            key = (
                item.get("codigo_tarefa"),
                item.get("maquina") or self.machine_display(item.get("maquina_sigmanest")),
                item.get("data_inicio") if separate_sessions else None,
            )
            groups.setdefault(key, []).append(item)

        result = []
        for items in groups.values():
            items.sort(key=lambda row: (
                self._program_order_key(row.get("programa")),
                int(row.get("sequencia_nesting") or 1),
                str(row.get("plano_hash") or ""),
            ))
            first = dict(items[0])
            programs = list(dict.fromkeys(
                str(item.get("programa") or "").strip()
                for item in items
                if str(item.get("programa") or "").strip()
            ))
            sheets = list(dict.fromkeys(
                str(item.get("nome_chapa") or "").strip()
                for item in items
                if str(item.get("nome_chapa") or "").strip()
            ))
            starts = [item.get("data_inicio") for item in items if item.get("data_inicio")]
            ends = [item.get("data_fim") for item in items if item.get("data_fim")]
            waiting = [item for item in items if item.get("status") == "Aguardando"]
            active = [item for item in items if item.get("status") == "Em processo"]
            completed = [item for item in items if item.get("status") == "Finalizado"]
            status = (
                "Em processo" if active
                else "Aguardando" if waiting
                else "Finalizado"
            )
            representative = active[0] if active else waiting[0] if waiting else completed[0]
            first.update({
                "id": representative.get("id"),
                "plano_hash": representative.get("plano_hash"),
                "status": status,
                "programa_atual": representative.get("programa"),
                "operador_inicio": representative.get("operador_inicio"),
                "operador_fim": representative.get("operador_fim"),
            })
            first.update({
                "plano_hashes": [item["plano_hash"] for item in items],
                "plano_hashes_aguardando": [item["plano_hash"] for item in waiting],
                # Simétrico ao de aguardando: quem consome a fila precisa saber
                # qual chapa já está aberta para não pedir para iniciá-la de novo.
                "plano_hashes_em_processo": [item["plano_hash"] for item in active],
                "apontamento_ids": [item["id"] for item in items if item.get("id") is not None],
                "apontamento_ids_em_processo": [item["id"] for item in active],
                "programas": programs,
                "programa": ", ".join(programs),
                "nome_chapa": ", ".join(sheets) or None,
                "nesting_count": len(items),
                # Cada linha projetada É uma chapa física do programa
                # (ProgramName + SheetName + RepeatID). A contagem vem do
                # SigmaNEST; nada é presumido como "1 nesting = 1 chapa".
                "quantidade_chapas": len(items),
                "chapas_por_programa": [
                    {
                        "programa": programa,
                        "chapas": sum(
                            1 for item in items
                            if str(item.get("programa") or "").strip() == programa
                        ),
                        "chapas_concluidas": sum(
                            1 for item in completed
                            if str(item.get("programa") or "").strip() == programa
                        ),
                    }
                    for programa in programs
                ],
                "nestings_concluidos": len(completed),
                "nestings_em_processo": len(active),
                "nestings_aguardando": len(waiting),
                "nesting_atual": len(completed) + 1 if active else None,
                "sequencia_nesting": len(items),
                "quantidade_processo": sum(
                    int(item.get("quantidade_processo") or 0) for item in items
                ),
                "tempo_previsto_segundos": sum(
                    float(item.get("tempo_previsto_segundos") or 0) for item in items
                ),
                "area_usada": sum(float(item.get("area_usada") or 0) for item in items),
                "data_programa": max(
                    (item.get("data_programa") for item in items if item.get("data_programa")),
                    default=None,
                ),
                "data_inicio": min(starts) if starts else None,
                "data_fim": max(ends) if ends else None,
                "nestings": [self._nesting_entry(item) for item in items],
            })
            task_code = str(first.get("codigo_tarefa") or "").strip()
            machine_sigmanest = (
                first.get("maquina_sigmanest")
                or self.machine_sigmanest(first.get("maquina"))
            )
            # A hierarquia operacional da tarefa: PLANO -> OP -> PRODUTO.
            # Tudo derivado do que já está projetado localmente; nenhum estado
            # novo é persistido por causa da apresentação.
            planos, ops_sem_plano = self._build_plans(
                items, machine_sigmanest, task_code, programs
            )
            first["planos"] = planos
            first["planos_count"] = len(planos)
            # Contrato de expansão da tarefa: o cliente recolhe/expande o que o
            # backend já entregou, sem uma segunda chamada por tarefa.
            first["expansivel"] = bool(planos)
            first["ops_sem_plano"] = ops_sem_plano
            # Contrato preservado: a lista plana de OPs da tarefa continua
            # existindo para o histórico e para o Destaque.
            first["ops_relacionadas"] = list(dict.fromkeys(
                op["codigo_op"]
                for grupo in (*(plano["ops"] for plano in planos), ops_sem_plano)
                for op in grupo
            ))
            # Cada nesting possui seus timestamps canônicos. O total da tarefa
            # é a soma dessas durações, não a janela entre o primeiro início e o
            # último fim (que incluía pausas, troca de programa e virada de dia).
            first["tempo_real_segundos"] = sum(
                max(0.0, float(item.get("tempo_real_segundos") or 0.0))
                for item in items
            )
            result.append(first)
        return result

    @staticmethod
    def _program_order_key(program):
        text = str(program or "").strip()
        parts = re.split(r"(\d+)", text.casefold())
        return tuple(
            (0, int(part)) if part.isdigit() else (1, part)
            for part in parts
            if part
        )

    def _record_event(self, event_type, row, message):
        try:
            self.db.registrar_evento_sistema(
                tipo=event_type,
                origem="CutService",
                referencia=f"{row.get('codigo_tarefa')}:{row.get('programa')}",
                mensagem=message,
                operador=self.operador,
                detalhes=json.dumps({
                    "apontamento_id": row.get("id"),
                    "apontamento_ids": row.get("apontamento_ids", []),
                    "plano_hash": row.get("plano_hash"),
                    "plano_hashes": row.get("plano_hashes", []),
                    "nestings": row.get("nesting_count", 1),
                    "maquina": row.get("maquina"),
                }, ensure_ascii=False, sort_keys=True),
                data_hora=self._now(),
            )
        except Exception:
            logging.exception("Falha ao registrar evento do apontamento de Corte")
