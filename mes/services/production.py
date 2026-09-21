"""Servicos de producao do MES."""

from dataclasses import dataclass
from datetime import datetime
import json
import logging
from typing import Optional

from app.core.normalization import limpa_codigo


@dataclass
class ProductionResult:
    ok: bool
    message: str
    code: str = ""
    data: Optional[dict] = None


class ProductionService:
    """Casos de uso de Destaque, despacho e movimentações auditadas."""

    def __init__(self, db, operador, maquinas_dobra=None, maquinas_usinagem=None, maquinas_serra=None, now_func=None):
        self.db = db
        self.operador = operador
        self.maquinas_dobra = maquinas_dobra or []
        self.maquinas_usinagem = maquinas_usinagem or []
        self.maquinas_serra = maquinas_serra or []
        self._now = now_func or datetime.now
        self.maquinas_por_setor = {
            "Dobra": self.maquinas_dobra,
            "Usinagem": self.maquinas_usinagem,
            "Serra": self.maquinas_serra,
        }

    def estado_destaque(self, tarefa_id, plano_hash=None):
        loader = getattr(self.db, "obter_estado_destaque", None)
        if callable(loader):
            estado = loader(tarefa_id, plano_hash) if plano_hash else loader(tarefa_id)
            if estado:
                return dict(estado)
        tarefa = self.db.buscar_tarefa_por_id(tarefa_id) if tarefa_id else None
        status = tarefa.get("status") if tarefa else None
        return {
            "tarefa_id": tarefa_id,
            "status_tarefa": status,
            "estado": {
                "Destacando": "inicio",
                "Finalizado": "fim",
                "Despachado": "fim",
            }.get(status, "aguardando"),
        }

    def tempos_destaque(self, tarefa_id, agora=None):
        """Expõe execução e parada do Destaque sem delegar cálculo à interface."""

        loader = getattr(self.db, "listar_eventos_destaque", None)
        events = list(loader(tarefa_id) or []) if callable(loader) else []
        now = agora or self._now().replace(microsecond=0)

        def as_datetime(value):
            if isinstance(value, datetime):
                return value
            if value in (None, ""):
                return None
            try:
                return datetime.fromisoformat(str(value).strip())
            except (TypeError, ValueError):
                return None

        ordered = sorted(
            (dict(event) for event in events if as_datetime(event.get("data_hora")) is not None),
            key=lambda event: (as_datetime(event.get("data_hora")), int(event.get("id") or 0)),
        )
        execution_seconds = 0
        stopped_seconds = 0
        mode = None
        cursor = None
        started_at = None
        for event in ordered:
            event_at = as_datetime(event.get("data_hora"))
            if cursor is not None and mode is not None:
                delta = max(0, int((event_at - cursor).total_seconds()))
                if mode == "execucao":
                    execution_seconds += delta
                elif mode == "parada":
                    stopped_seconds += delta
            state = str(event.get("estado") or "").casefold()
            if state in {"inicio", "retomada"}:
                mode = "execucao"
                started_at = started_at or event_at
            elif state == "parada":
                mode = "parada"
            elif state == "fim":
                mode = None
            cursor = event_at

        if cursor is not None and mode is not None:
            delta = max(0, int((now - cursor).total_seconds()))
            if mode == "execucao":
                execution_seconds += delta
            else:
                stopped_seconds += delta

        return {
            "availability": "disponivel" if ordered else "sem_registros",
            "started_at": started_at,
            "state_since": cursor,
            "current_mode": mode,
            "execution_seconds": execution_seconds,
            "stopped_seconds": stopped_seconds,
        }

    def _motivo_parada_destaque(self, codigo, comentario=None):
        finder = getattr(self.db, "buscar_status_recurso", None)
        row = finder(str(codigo or "").strip()) if callable(finder) else None
        if (
            not row
            or not row.get("habilitado")
            or row.get("oculto")
            or row.get("setup")
            or row.get("retrabalho")
            or row.get("grupo_codigo") == "0001"
        ):
            return None, "Selecione um motivo de parada válido do catálogo."
        if row.get("requer_comentario") and not str(comentario or "").strip():
            return None, "O motivo selecionado exige comentário."
        motivo = " - ".join(
            value
            for value in (
                str(row.get("codigo") or "").strip(),
                str(row.get("nome") or "").strip(),
            )
            if value
        )
        return dict(row), motivo

    def _grupo_destaque(self, tarefa_id):
        reader = getattr(self.db, "listar_fila_destaque", None)
        if not callable(reader):
            return None
        try:
            rows = reader(limite=10000) or []
        except TypeError:  # compatibilidade com repositórios de teste antigos
            rows = reader() or []
        return next(
            (
                dict(item)
                for item in rows
                if int(item.get("tarefa_id") or 0) == int(tarefa_id)
            ),
            None,
        )

    def _validar_escopo_destaque(self, tarefa_id, plano_hash=None):
        """Valida liberação de tarefa/plano usando a projeção canônica do Corte."""

        if not callable(getattr(self.db, "listar_fila_destaque", None)):
            return None
        grupo = self._grupo_destaque(tarefa_id)
        if grupo is None:
            return ProductionResult(
                False,
                "A tarefa não possui plano de Laser concluído e liberado pelo Corte.",
                code="destaque_nao_liberado",
            )
        if plano_hash:
            plano = next(
                (
                    item for item in grupo.get("planos", [])
                    if str(item.get("plano_hash") or "") == str(plano_hash).strip()
                ),
                None,
            )
            if plano is None or plano.get("status_corte") != "Finalizado":
                return ProductionResult(
                    False,
                    "O plano não está concluído no Corte ou não pertence ao Destaque.",
                    code="plano_destaque_indisponivel",
                )
            if plano.get("estado_destaque") == "fim":
                return ProductionResult(
                    False,
                    "Este plano já foi destacado e não pode ser apontado novamente.",
                    code="plano_destaque_duplicado",
                )
            return None
        if grupo.get("situacao") != "COMPLETA":
            return ProductionResult(
                False,
                "A tarefa inteira só pode ser destacada quando todos os planos de Laser estiverem concluídos no Corte.",
                code="tarefa_corte_incompleto",
                data=grupo,
            )
        if int(grupo.get("chapas_disponiveis") or 0) <= 0:
            return ProductionResult(
                False,
                "Todos os planos desta tarefa já foram destacados.",
                code="tarefa_destaque_duplicada",
                data=grupo,
            )
        return None

    def registrar_destacando(self, tarefa_id, codigo_tarefa, *, plano_hash=None):
        """Inicia o Destaque da tarefa inteira ou de uma chapa já cortada.

        O documento oficial de fluxo permite apontar "o plano ou a tarefa
        completa"; ``plano_hash`` escolhe o escopo, sem duplicar a máquina de
        estados.
        """

        if not tarefa_id:
            return ProductionResult(False, "Nenhuma tarefa carregada.", code="sem_tarefa")

        tarefa = self.db.buscar_tarefa_por_codigo(codigo_tarefa)
        if not tarefa:
            return ProductionResult(False, "Tarefa nao encontrada.", code="tarefa_nao_encontrada")
        invalid_scope = self._validar_escopo_destaque(tarefa_id, plano_hash)
        if invalid_scope is not None:
            return invalid_scope

        transition = getattr(self.db, "transicionar_destaque_tarefa", None)
        if callable(transition):
            estado = self.estado_destaque(tarefa_id, plano_hash).get("estado")
            if estado not in {"aguardando", "parada"}:
                return ProductionResult(
                    False,
                    "O destaque já está em execução ou já foi finalizado.",
                    code="status_existente",
                    data=tarefa,
                )
            atualizado = transition(
                tarefa_id,
                "inicio",
                self.operador,
                data_hora=self._now(),
                plano_hash=plano_hash,
            )
            if not atualizado:
                return ProductionResult(
                    False,
                    "A tarefa não pôde ser iniciada porque seu estado foi alterado.",
                    code="status_alterado",
                )
            retomada = atualizado.get("estado_destaque") == "retomada"
            event_type = "tarefa_destaque_retomado" if retomada else "tarefa_destacando"
            message = "Destaque retomado." if retomada else "Início do destaque registrado."
            self._registrar_evento(event_type, tarefa["codigo_tarefa"], message)
            return ProductionResult(True, message, data=atualizado)

        if tarefa.get("status"):
            return ProductionResult(False, "Tarefa ja possui status.", code="status_existente", data=tarefa)

        atualizado = self.db.registrar_transicao_tarefa(
            tarefa_id,
            status_esperado=None,
            novo_status="Destacando",
            operador=self.operador,
            setor="Destaque",
            motivo="Início do destaque",
        )
        if not atualizado:
            return ProductionResult(
                False,
                "A tarefa não pôde ser iniciada porque seu status foi alterado.",
                code="status_alterado",
            )
        self._registrar_evento("tarefa_destacando", tarefa["codigo_tarefa"], "Tarefa registrada como Destacando.")
        return ProductionResult(True, "Tarefa registrada como 'Destacando'.", data=tarefa)

    def registrar_parada_destaque(
        self,
        tarefa_id,
        codigo_tarefa,
        *,
        motivo_codigo,
        comentario=None,
        plano_hash=None,
    ):
        if not tarefa_id:
            return ProductionResult(False, "Nenhuma tarefa carregada.", code="sem_tarefa")
        tarefa = self.db.buscar_tarefa_por_codigo(codigo_tarefa)
        if not tarefa:
            return ProductionResult(False, "Tarefa nao encontrada.", code="tarefa_nao_encontrada")
        transition = getattr(self.db, "transicionar_destaque_tarefa", None)
        if not callable(transition):
            return ProductionResult(
                False,
                "O banco ainda não possui o fluxo de paradas do destaque.",
                code="fluxo_indisponivel",
            )
        status_row, motivo_or_error = self._motivo_parada_destaque(
            motivo_codigo,
            comentario,
        )
        if status_row is None:
            return ProductionResult(False, motivo_or_error, code="motivo_parada_invalido")
        if self.estado_destaque(tarefa_id, plano_hash).get("estado") not in {"inicio", "retomada"}:
            return ProductionResult(
                False,
                "O destaque precisa estar em execução para registrar uma parada.",
                code="status_invalido",
                data=tarefa,
            )
        atualizado = transition(
            tarefa_id,
            "parada",
            self.operador,
            codigo_status_recurso=status_row.get("codigo"),
            motivo=motivo_or_error,
            comentario=str(comentario or "").strip() or None,
            data_hora=self._now(),
            plano_hash=plano_hash,
        )
        if not atualizado:
            return ProductionResult(
                False,
                "A parada não foi registrada porque o estado da tarefa mudou.",
                code="status_alterado",
            )
        self._registrar_evento(
            "tarefa_destaque_parado",
            tarefa["codigo_tarefa"],
            "Parada do destaque registrada.",
            detalhes={"codigo_status_recurso": status_row.get("codigo")},
        )
        return ProductionResult(True, "Parada do destaque registrada.", data=atualizado)

    def registrar_finalizado(
        self, tarefa_id, codigo_tarefa, *, operador_identificacao=None,
        plano_hash=None,
    ):
        if not tarefa_id:
            return ProductionResult(False, "Nenhuma tarefa carregada.", code="sem_tarefa")

        tarefa = self.db.buscar_tarefa_por_codigo(codigo_tarefa)
        if not tarefa or tarefa.get("status") != "Destacando":
            return ProductionResult(False, "Tarefa deve estar 'Destacando' para finalizar.", code="status_invalido", data=tarefa)
        invalid_scope = self._validar_escopo_destaque(tarefa_id, plano_hash)
        if invalid_scope is not None:
            return invalid_scope

        transition = getattr(self.db, "transicionar_destaque_tarefa", None)
        if callable(transition):
            estado = self.estado_destaque(tarefa_id, plano_hash).get("estado")
            if estado == "parada":
                return ProductionResult(
                    False,
                    "Retome o destaque antes de registrar o fim.",
                    code="destaque_parado",
                    data=tarefa,
                )
            if estado not in {"inicio", "retomada"}:
                return ProductionResult(
                    False,
                    "A tarefa não possui um destaque em execução.",
                    code="status_invalido",
                    data=tarefa,
                )
            operador_evento = str(operador_identificacao or self.operador).strip() or self.operador
            atualizado = transition(
                tarefa_id,
                "fim",
                operador_evento,
                data_hora=self._now(),
                plano_hash=plano_hash,
            )
            if not atualizado:
                return ProductionResult(
                    False,
                    "O fim não foi registrado porque o estado da tarefa mudou.",
                    code="status_alterado",
                )
            if plano_hash:
                self._registrar_evento(
                    "tarefa_plano_destacado",
                    tarefa["codigo_tarefa"],
                    "Plano destacado.",
                )
                fechamento = self._fechar_tarefa_se_completa(
                    tarefa_id, tarefa, operador_evento, transition
                )
                if fechamento is not None:
                    return fechamento
                return ProductionResult(
                    True,
                    "Plano destacado. A tarefa continua aberta para os demais planos.",
                    code="plano_destacado",
                    data=atualizado,
                )
            self._registrar_evento(
                "tarefa_finalizada",
                tarefa["codigo_tarefa"],
                "Fim do destaque registrado.",
            )
            return ProductionResult(True, "Fim do destaque registrado.", data=atualizado)

        atualizado = self.db.registrar_transicao_tarefa(
            tarefa_id,
            status_esperado="Destacando",
            novo_status="Finalizado",
            operador=self.operador,
            setor="Organização de Pallets",
            motivo="Peças organizadas nos pallets",
        )
        if not atualizado:
            return ProductionResult(
                False,
                "A tarefa não pôde ser finalizada porque seu status foi alterado.",
                code="status_alterado",
            )
        self._registrar_evento("tarefa_finalizada", tarefa["codigo_tarefa"], "Tarefa finalizada e organizada em pallets.")
        return ProductionResult(True, "Tarefa finalizada. Peças prontas para despacho.", data=tarefa)

    def _fechar_tarefa_se_completa(self, tarefa_id, tarefa, operador, transition):
        """Encerra a tarefa quando o Destaque de todas as chapas terminou.

        A condição canônica de avanço da OP não muda: ela continua sendo
        ``tarefas.status = 'Finalizado'`` com todos os nestings ativos
        concluídos. O que muda é quem chega lá — antes só o fim manual da
        tarefa; agora também o último plano destacado.
        """

        if not callable(getattr(self.db, "listar_fila_destaque", None)):
            return None
        grupo = self._grupo_destaque(tarefa_id)
        if grupo is None:
            return None
        completa = (
            grupo.get("situacao") == "COMPLETA"
            and int(grupo.get("chapas_disponiveis") or 0) == 0
            and int(grupo.get("chapas_cortadas") or 0) > 0
        )
        if not completa:
            return None
        atualizado = transition(
            tarefa_id, "fim", operador, data_hora=self._now(), plano_hash=None
        )
        if not atualizado:
            return None
        self._registrar_evento(
            "tarefa_finalizada",
            tarefa["codigo_tarefa"],
            "Todos os planos foram destacados; tarefa finalizada.",
        )
        return ProductionResult(
            True,
            "Último plano destacado. Tarefa finalizada.",
            code="tarefa_finalizada",
            data=atualizado,
        )

    def registrar_despachado(self, tarefa_id, codigo_tarefa):
        if not tarefa_id:
            return ProductionResult(False, "Nenhuma tarefa carregada.", code="sem_tarefa")

        tarefa = self.db.buscar_tarefa_por_codigo(codigo_tarefa)
        if not tarefa or tarefa.get("status") != "Finalizado":
            return ProductionResult(False, "Tarefa deve estar 'Finalizado' para despachar.", code="status_invalido", data=tarefa)

        despachado = self.db.despachar_tarefa(
            tarefa_id,
            self.operador,
            maquinas_dobra=self.maquinas_dobra,
            maquinas_usinagem=self.maquinas_usinagem,
            maquinas_serra=self.maquinas_serra,
        )
        if not despachado:
            return ProductionResult(
                False,
                "A tarefa não pôde ser despachada porque seu status foi alterado.",
                code="status_alterado",
            )
        self._registrar_evento("tarefa_despachada", tarefa["codigo_tarefa"], "Tarefa despachada.")
        return ProductionResult(True, "Tarefa despachada. OPs movidas conforme setor.", data=tarefa)

    def corrigir_op(self, op_id, codigo_op, setor_atual, qtd_atual, novo_setor, nova_quantidade, tarefa_id):
        try:
            nova_qtd = int(nova_quantidade)
            qtd_atual_int = int(qtd_atual)
            if nova_qtd <= 0:
                raise ValueError
        except (TypeError, ValueError):
            return ProductionResult(False, "Quantidade deve ser inteiro positivo.", code="quantidade_invalida")

        atualizado = self.db.corrigir_op_com_historico(
            op_id=op_id,
            codigo_op=codigo_op,
            setor_esperado=setor_atual,
            quantidade_esperada=qtd_atual_int,
            novo_setor=novo_setor,
            nova_quantidade=nova_qtd,
            operador=self.operador,
            tarefa_id=tarefa_id,
        )
        if not atualizado:
            return ProductionResult(
                False,
                "A OP não pôde ser corrigida porque seus dados foram alterados.",
                code="dados_alterados",
            )
        self._registrar_evento(
            "op_corrigida",
            codigo_op,
            "OP corrigida manualmente.",
            detalhes={"setor_anterior": setor_atual, "setor_novo": novo_setor, "qtd_anterior": qtd_atual_int, "qtd_nova": nova_qtd},
        )
        return ProductionResult(True, "OP atualizada.", data={"nova_quantidade": nova_qtd})

    def registrar_movimentacao(self, op, maquina):
        codigo_op = limpa_codigo(op)
        if not codigo_op or not maquina:
            return ProductionResult(False, "OP e maquina obrigatorios.", code="campos_obrigatorios")

        row = self._buscar_contexto_op(codigo_op)
        tarefa_id = row["tarefa_id"] if row else None
        peca = row["id_peca"] if row else ""

        self.db.inserir_historico(codigo_op, "Movimentação", maquina, "", 1, self.operador, peca, tarefa_id)
        self._registrar_evento(
            "op_movimentada",
            codigo_op,
            f"OP registrada em {maquina}.",
            detalhes={"maquina": maquina, "tarefa_id": tarefa_id},
        )
        return ProductionResult(True, "Movimentacao registrada.", data={"op": codigo_op, "maquina": maquina, "tarefa_id": tarefa_id, "peca": peca})

    def _buscar_contexto_op(self, codigo_op):
        """Resolve a OP operacional primeiro e usa o PCP apenas como cadastro."""

        row = self.db.buscar_op_por_codigo(codigo_op)
        if row:
            return row
        buscar_catalogo = getattr(self.db, "buscar_op_catalogo", None)
        catalog = buscar_catalogo(codigo_op) if callable(buscar_catalogo) else None
        if not catalog:
            return None
        return {
            "tarefa_id": None,
            "id_peca": catalog.get("produto_descricao") or "",
            "quantidade_original": catalog.get("quantidade") or 1,
            "quantidade_atual": catalog.get("quantidade") or 1,
            "origem": "catalogo_pcp",
        }

    def _registrar_evento(self, tipo, referencia, mensagem, detalhes=None):
        registrar = getattr(self.db, "registrar_evento_sistema", None)
        if not registrar:
            return
        try:
            registrar(
                tipo=tipo,
                origem="ProductionService",
                referencia=referencia,
                mensagem=mensagem,
                operador=self.operador,
                detalhes=json.dumps(detalhes or {}, ensure_ascii=False, sort_keys=True),
                data_hora=self._now(),
            )
        except Exception:
            logging.exception("Falha ao registrar evento de producao")
