"""Fila manual por recurso: o líder escolhe a ordem e puxa OPs para o recurso.

Regra de negócio aqui; persistência em ``app/database/manual_queue_repository.py``
e leitura dos cards em ``OperatorFlowService.listar_cartoes`` (a fila que o
operador vê é a mesma que o líder edita, sem segunda fonte de verdade).

Decisões do usuário (15/10/2026):
- só a PRÓXIMA operação liberada da OP pode ser puxada, de qualquer recurso;
- a ordem vale até a OP sair da fila (nada zera por dia);
- Corte e Destaque ficam de fora (fila automática).
"""

from __future__ import annotations

from app.core.normalization import limpa_codigo
from mes.services.operator_flow import OperatorFlowService

_ESTADOS_EM_EXECUCAO = frozenset({"Em processo", "Parada", "Setup", "Retrabalho"})


class ManualQueueError(Exception):
    """Erro de regra da fila manual (o transporte devolve 409 com ``code``)."""

    def __init__(self, code, message, *, status_code=409, details=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details


class ManualQueueService:
    def __init__(self, db, usuario, now_func=None):
        self.db = db
        self.usuario = str(usuario or "Líder").strip() or "Líder"
        self._flow = OperatorFlowService(db, self.usuario, now_func=now_func)

    # ---- leitura -----------------------------------------------------------------

    def listar(self, recurso):
        """Fila do recurso na ordem em que o operador a vê.

        ``recurso`` é um item de ``app.core.areas.recursos_da_area``.
        """

        cards = self._flow.listar_cartoes(recurso["setor"], recurso["station"])["queue"]
        itens = [
            {
                "entry_id": card.get("fila_manual_id"),
                "operation_id": card["catalogo_operacao_id"],
                "op": str(card.get("op") or card.get("codigo_op") or ""),
                "operation": card.get("operation") or "",
                "product": card.get("product") or "",
                "description": card.get("description") or "",
                "qty": card.get("qty") or 0,
                "fixada": bool(card.get("fixada")),
                "origem_recurso": card.get("origem_recurso"),
                "posicao": card.get("posicao_manual"),
            }
            for card in cards
            if card.get("catalogo_operacao_id") is not None
        ]
        # A posição gravada só é recompactada na próxima escrita; a leitura
        # mostra sempre 1, 2, 3... entre as OPs fixadas.
        for posicao, item in enumerate((i for i in itens if i["fixada"]), start=1):
            item["posicao"] = posicao
        return {"resource": recurso["resource"], "items": itens}

    # ---- escrita -----------------------------------------------------------------

    def adicionar(self, recurso, op):
        codigo = limpa_codigo(op)
        if not codigo:
            raise ManualQueueError("fila_manual_op_invalida", "Informe o número da OP.")
        pcp = self.db.buscar_op_pcp_ativa(codigo)
        if pcp is None:
            raise ManualQueueError(
                "fila_manual_op_inexistente", f"OP {codigo} não encontrada.", status_code=409
            )
        if not pcp.get("ativo"):
            raise ManualQueueError(
                "fila_manual_op_inativa", f"OP {codigo} não está ativa."
            )

        operacao_id = self._operacao_a_fixar(codigo, recurso)
        self.db.adicionar_fila_manual(
            operacao_id["id"],
            codigo,
            recurso["setor"],
            recurso["resource"],
            self.usuario,
        )
        return self.listar(recurso)

    def reordenar(self, recurso, operation_ids):
        atuais = {
            item["operation_id"]: item for item in self.listar(recurso)["items"]
        }
        ordem, vistos = [], set()
        for operation_id in operation_ids:
            if operation_id in atuais and operation_id not in vistos:
                vistos.add(operation_id)
                ordem.append((operation_id, limpa_codigo(atuais[operation_id]["op"])))
        self.db.reordenar_fila_manual(
            recurso["setor"], recurso["resource"], ordem, self.usuario
        )
        return self.listar(recurso)

    def remover(self, recurso, entry_id):
        if not self.db.remover_fila_manual(entry_id, recurso["resource"], self.usuario):
            raise ManualQueueError(
                "fila_manual_entrada_inexistente",
                "Esta OP não está fixada na fila deste recurso.",
                status_code=404,
            )
        return self.listar(recurso)

    # ---- regra -------------------------------------------------------------------

    def _operacao_a_fixar(self, codigo, recurso):
        """Operação da OP que o líder pode fixar neste recurso, ou erro de regra."""

        apontamentos = self.db.listar_apontamentos_por_op(codigo) or []
        identidade = self._flow._identidade_estacao(recurso["resource"])
        for linha in apontamentos:
            estado = linha.get("status")
            if estado in _ESTADOS_EM_EXECUCAO:
                onde = str(linha.get("maquina") or "").strip() or "outro recurso"
                raise ManualQueueError(
                    "fila_manual_op_em_execucao",
                    f"Já em execução em {onde} desde {self._hora(linha)}.",
                    details={"op": codigo, "recurso_ativo": onde},
                )
            if estado == "Aguardando":
                if self._flow._identidade_estacao(linha.get("maquina")) != identidade:
                    onde = str(linha.get("maquina") or "").strip() or "outro recurso"
                    raise ManualQueueError(
                        "fila_manual_op_aguardando_em_outro_recurso",
                        f"OP {codigo} já está aguardando em {onde}.",
                        details={"op": codigo, "recurso_ativo": onde},
                    )
                if linha.get("catalogo_operacao_id") is None:
                    raise ManualQueueError(
                        "fila_manual_sem_operacao",
                        f"OP {codigo} está na fila sem vínculo com o roteiro.",
                    )
                # Já aguarda neste recurso: só fixa a posição.
                return {"id": linha["catalogo_operacao_id"]}

        candidatas = self.db.listar_proximas_operacoes_roteiro(codigo_op=codigo) or []
        if not candidatas:
            raise self._sem_proxima_operacao(codigo, apontamentos)
        candidata = dict(candidatas[0])
        if candidata.get("marco_terminal") or candidata.get("inspecao_qualidade"):
            raise ManualQueueError(
                "fila_manual_operacao_nao_apontavel",
                f"A próxima etapa da OP {codigo} não é apontada em recurso.",
            )
        return {"id": candidata["id"]}

    def _sem_proxima_operacao(self, codigo, apontamentos):
        roteiro = list(self.db.listar_operacoes_para_op(codigo) or [])
        if not roteiro:
            return ManualQueueError(
                "fila_manual_op_sem_roteiro", f"OP {codigo} não tem roteiro importado."
            )
        finalizadas = {
            linha.get("catalogo_operacao_id")
            for linha in apontamentos
            if linha.get("status") == "Finalizado"
        }
        pendente = next((linha for linha in roteiro if linha["id"] not in finalizadas), None)
        if pendente is None:
            return ManualQueueError(
                "fila_manual_op_concluida",
                f"OP {codigo} já teve todas as etapas concluídas.",
            )
        numero = str(pendente.get("numero_operacao") or "").strip()
        nome = str(pendente.get("descricao_operacao") or "").strip()
        etapa = " - ".join(parte for parte in (numero, nome) if parte) or "anterior"
        return ManualQueueError(
            "fila_manual_etapa_anterior_pendente",
            f"OP {codigo} aguarda a etapa {etapa} ser concluída.",
            details={"op": codigo, "etapa_pendente": etapa},
        )

    @staticmethod
    def _hora(linha):
        momento = linha.get("data_inicio") or linha.get("data_entrada")
        return momento.strftime("%H:%M") if hasattr(momento, "strftime") else "início não registrado"
