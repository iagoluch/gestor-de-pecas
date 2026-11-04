"""Consulta de OP (gestão à vista) e etapa adicionada no Gestor ao roteiro.

Só lê o que o Protheus mandou e o que o Gestor executou. A única escrita é a
etapa adicionada (migration 72): apontável como qualquer operação, marcada
"adicionada no Gestor", auditada e NUNCA enviada ao Protheus. Etapa do Protheus
não é editável aqui. A permissão (PCP, engenharia de manufatura e admin) é
decidida pelo backend (``app.core.permissions.can_manage_route_steps``).
"""

from __future__ import annotations

import logging
from types import SimpleNamespace

from app.core.normalization import limpa_codigo
from app.core.operator_sectors import is_apontavel_resource
from app.core.permissions import can_manage_route_steps
from app.core.resource_mapping import resource_canonical_sector
from mes.services.change_audit import auditar
from mes.services.order_provisioning import OrderProvisioningResult

ENTIDADE_AUDITORIA = "roteiro_etapa"
#: Tempo que o Protheus manda para "não configurado" (a OP chega com 0,01).
TEMPO_NAO_CONFIGURADO = 0.01
NOTA_TEMPO_NAO_CADASTRADO = (
    "Tempo padrão não cadastrado no Protheus. "
    "A engenharia de manufatura ajusta direto no ERP."
)
#: Corte e Destaque têm fluxo próprio (plano SigmaNEST / tempo do Destaque).
SETORES_FORA_DA_ETAPA = ("corte", "destaque")
LIMITE_BUSCA = 20


class RouteStepError(Exception):
    def __init__(self, code, message, *, status_code=409):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def _tempo_padrao(valor):
    try:
        segundos = float(valor) if valor is not None else None
    except (TypeError, ValueError):
        segundos = None
    if segundos is None or segundos <= TEMPO_NAO_CONFIGURADO:
        return {"segundos": None, "disponivel": False, "nota": NOTA_TEMPO_NAO_CADASTRADO}
    return {"segundos": segundos, "disponivel": True, "nota": None}


def _situacao(linha):
    if linha["marco_terminal"]:
        return "Marco terminal (Protheus)"
    if linha["inspecao_qualidade"]:
        return "Inspeção da Qualidade"
    if not linha["ativo"]:
        return "Desativada" if linha["etapa_gestor"] else "Substituída no Protheus"
    return linha["execucao_status"] or "Não iniciada"


def _linha_roteiro(linha):
    return {
        "id": int(linha["id"]),
        "ordem": linha["ordem"],
        "numero_operacao": linha["numero_operacao"],
        "descricao": linha["descricao_operacao"],
        "setor": linha["tipo_setor"],
        "recurso_codigo": linha["codigo_recurso"],
        "recurso_nome": linha["recurso_nome"],
        "tempo_padrao": _tempo_padrao(linha["tempo_medio_segundos"]),
        "situacao": _situacao(linha),
        "quantidade_boa": int(linha["quantidade_boa"] or 0),
        "origem": "gestor" if linha["etapa_gestor"] else "protheus",
        "ativo": bool(linha["ativo"]),
        "marco_terminal": bool(linha["marco_terminal"]),
        "inspecao_qualidade": bool(linha["inspecao_qualidade"]),
        "adicionada_por": linha["adicionada_por_nome"],
        "adicionada_em": linha["adicionada_em"],
        "motivo_adicao": linha["motivo_adicao"],
        "desativada_por": linha["desativada_por_nome"],
        "desativada_em": linha["desativada_em"],
        "motivo_desativacao": linha["motivo_desativacao"],
        "apos_operacao_id": linha["apos_operacao_id"],
    }


def _texto(valor, rotulo, minimo, maximo):
    texto = " ".join(str(valor or "").split())
    if not minimo <= len(texto) <= maximo:
        raise RouteStepError(
            "route_step_invalid_text",
            f"{rotulo} deve ter entre {minimo} e {maximo} caracteres.",
            status_code=422,
        )
    return texto


class OrderRouteService:
    def __init__(self, db, user_id=None, user_name=None, user_role=None,
                 assigned_level=None, now_func=None):
        self.db = db
        self.user = SimpleNamespace(id=user_id, name=user_name)
        self.role = user_role
        self.assigned_level = assigned_level
        self.now_func = now_func

    @property
    def pode_alterar(self):
        return can_manage_route_steps(self.role, self.assigned_level)

    def _exigir_permissao(self):
        if not self.pode_alterar:
            raise RouteStepError(
                "route_step_access_denied",
                "Só o PCP, a engenharia de manufatura e a conta administradora"
                " alteram o roteiro de uma OP.",
                status_code=403,
            )

    def _agora(self):
        return self.now_func() if callable(self.now_func) else None

    def buscar(self, termo):
        termo = str(termo or "").strip()
        if len(termo) < 2:
            return []
        return self.db.buscar_ops_para_consulta(termo, LIMITE_BUSCA)

    def _op(self, codigo):
        codigo = limpa_codigo(codigo)
        op = self.db.obter_op_para_consulta(codigo) if codigo else None
        if op is None:
            raise RouteStepError("order_not_found", "OP não encontrada.", status_code=404)
        return op

    def recursos_para_etapa(self):
        """Só recursos apontáveis (regra "apontáveis vs. só sincronizados")."""

        return [
            {"codigo": r["codigo"], "nome": r["nome"], "setor": r["tipo_setor"]}
            for r in self.db.listar_recursos_catalogo_para_etapa()
            if str(r.get("tipo_setor") or "").strip().casefold() not in SETORES_FORA_DA_ETAPA
            and is_apontavel_resource(r["codigo"], r["nome"])
        ]

    def _situacao_no_sistema(self, op):
        """Se a OP já passou pelo Gestor. ``op`` é a linha local ou ``None`` (só no Protheus)."""

        if op is None:
            return {"situacao": "so_protheus", "apontamentos": 0, "iniciados": 0,
                    "primeira_entrada": None, "ultima_atividade": None, "coletada_em": None}
        resumo = self.db.resumir_passagem_op(op["codigo_op"])
        iniciados = int(resumo.get("iniciados") or 0)
        return {
            "situacao": "ja_passou" if iniciados else "no_sistema_sem_apontamento",
            "apontamentos": int(resumo.get("apontamentos") or 0),
            "iniciados": iniciados,
            "primeira_entrada": resumo.get("primeira_entrada"),
            "ultima_atividade": resumo.get("ultima_atividade"),
            "coletada_em": op.get("sincronizado_em"),
        }

    def consultar_protheus(self, codigo_op, provisioning):
        """Coleta a OP no Protheus (se o Gestor ainda não a tem) e diz se ela já passou pelo sistema.

        O estado do Gestor é lido ANTES da coleta: é ele que responde "já estava aqui?".
        """

        codigo = limpa_codigo(codigo_op)
        if not codigo:
            raise RouteStepError("order_not_found", "Informe o código da OP.", status_code=422)
        antes = self.db.obter_op_para_consulta(codigo)
        try:
            resultado = provisioning.provision(codigo)
        except Exception:
            logging.exception("Falha ao consultar a OP no Protheus.")
            resultado = OrderProvisioningResult(
                op=codigo, status="indisponivel", found=False,
                message=provisioning.unavailable_message,
            )
        op = antes or (self.db.obter_op_para_consulta(codigo) if resultado.found else None)
        return {
            "op": codigo,
            "estava_no_gestor": antes is not None,
            "protheus": {
                "status": resultado.status,
                "consultado": antes is None and resultado.status != "indisponivel",
                "message": resultado.message,
            },
            "system": self._situacao_no_sistema(op),
        }

    def consultar(self, codigo_op):
        op = self._op(codigo_op)
        roteiro = [_linha_roteiro(l) for l in self.db.listar_roteiro_para_consulta(op["codigo_op"])]
        historico = self.db.listar_auditoria(
            entidade=ENTIDADE_AUDITORIA, chave=op["codigo_op"], limite=100
        )
        payload = {
            "order": {
                chave: op.get(chave)
                for chave in (
                    "codigo_op", "produto_codigo", "produto_descricao", "quantidade",
                    "unidade", "status_pcp", "filial", "data_emissao", "data_liberacao",
                    "inicio_planejado", "fim_planejado", "prioridade", "sincronizado_em",
                )
            },
            "route": roteiro,
            "history": list(historico or []),
            "system": self._situacao_no_sistema(op),
            "permissions": {"can_add_step": self.pode_alterar},
            "add_options": None,
        }
        if self.pode_alterar:
            payload["add_options"] = {
                "after_operations": [
                    {"id": l["id"], "numero_operacao": l["numero_operacao"], "descricao": l["descricao"]}
                    for l in roteiro
                    if l["ativo"] and not l["marco_terminal"] and not l["inspecao_qualidade"]
                ],
                "resources": self.recursos_para_etapa(),
            }
        return payload

    def adicionar_etapa(self, codigo_op, *, apos_operacao_id, descricao, recurso, motivo):
        self._exigir_permissao()
        op = self._op(codigo_op)
        descricao = _texto(descricao, "A descrição", 3, 120)
        motivo = _texto(motivo, "O motivo", 3, 500)
        escolhido = next(
            (r for r in self.recursos_para_etapa() if r["codigo"] == str(recurso or "").strip()),
            None,
        )
        if escolhido is None:
            raise RouteStepError(
                "route_step_resource_not_pointable",
                "Escolha um recurso apontável (posto que algum operador aponta).",
                status_code=422,
            )
        setor = resource_canonical_sector(escolhido["codigo"], escolhido["setor"])
        try:
            linha, anterior = self.db.inserir_etapa_gestor(
                codigo_op=op["codigo_op"], apos_operacao_id=apos_operacao_id,
                descricao=descricao, tipo_setor=setor, codigo_recurso=escolhido["codigo"],
                motivo=motivo, usuario_id=self.user.id, usuario_nome=self.user.name,
                agora=self._agora(),
            )
        except LookupError as error:
            raise RouteStepError(
                "route_step_anchor_not_found",
                "A operação escolhida não faz parte do roteiro ativo desta OP.",
                status_code=422,
            ) from error
        auditar(
            self.db, self.user, ENTIDADE_AUDITORIA, op["codigo_op"],
            depois={
                "codigo_op": op["codigo_op"], "numero_operacao": linha["numero_operacao"],
                "descricao_operacao": descricao, "setor": setor,
                "recurso": escolhido["codigo"], "apos_operacao": anterior,
                "motivo": motivo, "ativo": True,
            },
        )
        return {"id": int(linha["id"]), "numero_operacao": linha["numero_operacao"]}

    def desativar_etapa(self, codigo_op, etapa_id, *, motivo):
        self._exigir_permissao()
        op = self._op(codigo_op)
        motivo = _texto(motivo, "O motivo", 3, 500)
        try:
            etapa = self.db.desativar_etapa_gestor(
                codigo_op=op["codigo_op"], etapa_id=etapa_id, motivo=motivo,
                usuario_nome=self.user.name, agora=self._agora(),
            )
        except ValueError as error:
            raise RouteStepError(
                "route_step_already_pointed",
                "Esta etapa já tem apontamento e não pode ser desativada.",
            ) from error
        if etapa is None:
            raise RouteStepError(
                "route_step_not_found",
                "Só etapas adicionadas no Gestor e ainda ativas podem ser desativadas;"
                " etapas do Protheus não são alteradas aqui.",
                status_code=404,
            )
        base = {
            "codigo_op": op["codigo_op"], "numero_operacao": etapa["numero_operacao"],
            "descricao_operacao": etapa["descricao_operacao"], "setor": etapa["tipo_setor"],
            "recurso": etapa["codigo_recurso"],
        }
        auditar(
            self.db, self.user, ENTIDADE_AUDITORIA, op["codigo_op"],
            antes={**base, "ativo": True},
            depois={**base, "motivo": motivo, "ativo": False},
        )
        return {"id": int(etapa_id), "ativo": False}
