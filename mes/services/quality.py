"""Caso de uso da inspeção dimensional da Qualidade.

Regra funcional desta etapa, em uma frase: a Qualidade é a execução da
operação ``INSPECAO`` do roteiro, feita peça por peça contra as cotas do
produto, dentro da experiência normal do operador.

Três fronteiras importam aqui:

* **Origem da OP.** Nenhuma segunda fonte de OP é criada. A fila lê
  ``catalogo_pcp_ops`` + ``catalogo_operacoes_op``, exatamente como o resto do
  Gestor.
* **Movimento empresarial.** A inspeção não possui transporte próprio para o
  TOTVS. Ela abre e fecha a operação ``INSPECAO`` pelo ``OperatorFlowService``,
  e o evento canônico resultante é que aciona a outbox já homologada. Preencher
  cota, marcar Não conforme ou abrir RNC **não** gera mensagem alguma.
* **Autoridade.** Toda regra vive aqui e no banco. O React apresenta e coleta.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
import logging

from app.core.normalization import limpa_codigo
from app.core.permissions import quality_sector_for_user_level
from app.core.quality import (
    QUALITY_APPOINTMENT_SECTOR,
    QUALITY_MEASURE_NON_CONFORMING,
    QUALITY_RESULT_APPROVED,
    QUALITY_RESULT_REWORK,
    QUALITY_RESULT_SCRAP,
    normalize_piece_result,
    sector_has_quality,
)
from mes.domain import OperatorState, operator_state_from_status
# ``template_publico`` é projeção pura e vive no domínio desde a Wave 6B, para
# que o portão da primeira peça publique o mesmo checklist sem copiá-lo. O
# reexport mantém o contrato de importação dos roteadores já existentes.
from mes.domain.quality_measures import (
    evaluate_measure,
    resolve_checklist_measures,
    template_publico,
)
from mes.services.operator_flow import OperatorFlowService


@dataclass(frozen=True)
class QualityResult:
    ok: bool
    message: str
    code: str = ""
    data: dict | None = None


def _fail(code, message, data=None):
    return QualityResult(False, message, code, data)


def _texto(value, limite=120):
    return str(value or "").strip()[:limite]


def desenho_publico(desenho):
    """Metadado do desenho mais recente; o arquivo é servido por rota própria."""

    if not desenho:
        return None
    return {
        "id": desenho.get("id"),
        "produto": desenho.get("produto_codigo"),
        "filename": desenho.get("filename"),
        "versao": int(desenho.get("versao") or 1),
        "size_bytes": int(desenho.get("size_bytes") or 0),
        "enviado_em": desenho.get("enviado_em"),
        "enviado_por": desenho.get("enviado_por_nome"),
    }


class QualityInspectionService:
    """Orquestra template, inspeção peça a peça, RNC e histórico."""

    def __init__(self, db, operador, *, now_func=None, usuario_id=None, nivel=""):
        self.db = db
        self.operador = str(operador or "Operador").strip() or "Operador"
        self.usuario_id = usuario_id
        self.nivel = str(nivel or "").strip()
        self._now = now_func or (lambda: datetime.now().replace(microsecond=0))

    # ------------------------------------------------------------------
    # Fila de OPs
    # ------------------------------------------------------------------
    @staticmethod
    def _pertence_ao_setor(row, setor):
        """A inspeção é do setor que produziu a peça, não da Qualidade em bloco.

        A operação de inspeção chega do TOTVS sem ``tipo_setor`` próprio; quem
        a torna elegível é a etapa apontável anterior, e é o setor dela que
        manda. Uma peça pronta na Dobra não aparece na Qualidade da Usinagem.
        Origem não resolvida continua visível em todos os setores: some da fila
        seria pior do que aparecer no lugar errado, e o caso fica auditável.
        """

        origem = _texto(row.get("tipo_setor_origem"))
        if not origem:
            return True
        return origem.casefold() == _texto(setor).casefold()

    def _exigir_setor(self, sessao):
        """Revalida, na escrita, o mesmo recorte que a abertura já aplica.

        ``abrir_inspecao`` recusa OP de outro setor, mas as rotas seguintes
        recebem apenas o ``inspecao_id``: sem esta checagem, trocar o id na URL
        contornaria a fronteira e deixaria um setor medir, reprovar, abrir RNC
        e finalizar a inspeção de outro. O setor dono vem gravado na sessão
        desde a abertura — não é redescoberto peça a peça, justamente para não
        bloquear o operador certo quando a OP já saiu da fila.

        Devolve ``None`` quando a operação é permitida. Nível sem setor de
        Qualidade não é recusado aqui: o roteador já barra o acesso por papel,
        e chamadas internas do domínio não possuem usuário para comparar.
        """

        sector = quality_sector_for_user_level(self.nivel)
        if sector is None or self._pertence_ao_setor(sessao, sector.name):
            return None
        return _fail(
            "qualidade_inspecao_outro_setor",
            "Esta inspeção pertence a "
            f"{_texto(sessao.get('tipo_setor_origem'))}, não a {sector.name}.",
        )

    def listar_fila(self, setor, *, busca=None, recurso=None):
        """Fila de inspeção do setor, já filtrada e resumida para a tela."""

        if not sector_has_quality(setor):
            return {
                "items": [],
                "resumo": self._resumo_vazio(),
                "recursos": [],
                "busca": None,
            }
        rows = [
            dict(row)
            for row in (self.db.listar_ops_elegiveis_inspecao() or ())
            if self._pertence_ao_setor(row, setor)
        ]
        recursos = sorted(
            {
                _texto(row.get("codigo_recurso"))
                for row in rows
                if _texto(row.get("codigo_recurso"))
            }
        )
        alvo = _texto(recurso)
        if alvo:
            rows = [
                row
                for row in rows
                if _texto(row.get("codigo_recurso")).casefold() == alvo.casefold()
            ]
        termo = _texto(busca).casefold()
        if termo:
            rows = [row for row in rows if self._corresponde_busca(row, termo)]
        items = [self._item_fila(row) for row in rows]
        return {
            "items": items,
            "resumo": self.resumo(setor),
            "recursos": recursos,
            # Busca vazia não é um erro: é um estado do roteiro, e o operador
            # merece saber qual deles. Nenhuma destas checagens sai do Gestor.
            "busca": self._diagnosticar_busca(busca) if (busca and not items) else None,
        }

    def _diagnosticar_busca(self, busca):
        """Explica localmente por que a OP pesquisada não está na fila.

        A Qualidade nunca faz pull no ERP. Quando o fluxo chega na inspeção a OP
        já existe aqui, com roteiro sincronizado e execução anterior registrada;
        uma OP ausente é informação sobre o estado do Gestor, não um motivo para
        acionar o Protheus.
        """

        codigo = limpa_codigo(busca)
        if not codigo:
            return {
                "codigo": "qualidade_busca_sem_resultado",
                "message": "Nenhuma OP da fila corresponde à pesquisa.",
            }
        planejada = self.db.buscar_op_planejada(codigo)
        if planejada is None:
            return {
                "codigo": "qualidade_op_indisponivel",
                "message": "OP não disponível para inspeção.",
            }
        sessao = self.db.buscar_ultima_inspecao(codigo)
        if sessao is not None and sessao.get("status") == "CONCLUIDA":
            return {
                "codigo": "qualidade_inspecao_concluida",
                "message": "Inspeção desta OP já concluída.",
            }
        return {
            "codigo": "qualidade_op_nao_aguardando",
            "message": "OP ainda não está aguardando inspeção.",
        }

    @staticmethod
    def _corresponde_busca(row, termo):
        campos = (
            row.get("codigo_op"),
            row.get("produto_codigo"),
            row.get("produto_descricao"),
            row.get("descricao_operacao"),
            row.get("codigo_recurso"),
            row.get("recurso_nome"),
        )
        if any(termo in str(valor or "").casefold() for valor in campos):
            return True
        for data in (row.get("inicio_planejado"), row.get("data_liberacao")):
            if data is None:
                continue
            texto = data.strftime("%d/%m/%Y") if hasattr(data, "strftime") else str(data)
            if termo in texto.casefold():
                return True
        return False

    @staticmethod
    def _item_fila(row):
        quantidade = int(row.get("quantidade") or 0)
        registradas = int(row.get("pecas_registradas") or 0)
        return {
            "quantidade_planejada": int(
                row.get("quantidade_planejada") or quantidade
            ),
            "quantidade_aprovada": int(row.get("quantidade_aprovada") or 0),
            "op": _texto(row.get("codigo_op"), 60),
            "operacao": _texto(row.get("numero_operacao"), 20),
            "descricao": _texto(row.get("produto_descricao"), 200),
            "produto": _texto(row.get("produto_codigo"), 60),
            "recurso": _texto(row.get("codigo_recurso"), 60),
            "recurso_nome": _texto(row.get("recurso_nome"), 120),
            "quantidade": quantidade,
            "inspecionadas": registradas,
            "pendentes": max(quantidade - registradas, 0),
            "data": row.get("inicio_planejado") or row.get("data_liberacao"),
            "inspecao_id": row.get("inspecao_id"),
            "em_andamento": bool(row.get("inspecao_id")),
        }

    @staticmethod
    def _resumo_vazio():
        return {"aguardando": 0, "aprovadas": 0, "retrabalho": 0, "refugo": 0}

    def resumo(self, setor):
        """Os quatro indicadores da tela, sempre do escopo do setor atual."""

        if not sector_has_quality(setor):
            return self._resumo_vazio()
        registrado = dict(
            self.db.resumo_qualidade(
                setor=QUALITY_APPOINTMENT_SECTOR, setor_origem=setor
            )
            or {}
        )
        pendente_em_fila = int(self.db.contar_pendentes_inspecao() or 0)
        return {
            "aguardando": pendente_em_fila,
            "aprovadas": int(registrado.get("aprovadas") or 0),
            "retrabalho": int(registrado.get("retrabalho") or 0),
            "refugo": int(registrado.get("refugo") or 0),
        }

    # ------------------------------------------------------------------
    # Abertura da inspeção
    # ------------------------------------------------------------------
    def abrir_inspecao(self, op, setor, *, badges=None):
        """Abre a inspeção da OP e inicia a operação INSPECAO pelo fluxo canônico."""

        if not sector_has_quality(setor):
            return _fail(
                "qualidade_setor_indisponivel",
                f"O setor {setor} não possui inspeção de qualidade habilitada.",
            )
        codigo = limpa_codigo(op)
        if not codigo:
            return _fail("qualidade_op_obrigatoria", "Informe a OP a inspecionar.")
        operacao = self.db.buscar_operacao_inspecao(codigo)
        if operacao is None:
            return _fail(
                "qualidade_operacao_inexistente",
                "Esta OP não possui operação de inspeção no roteiro.",
            )
        elegivel = next(
            (
                row
                for row in (self.db.listar_ops_elegiveis_inspecao() or ())
                if limpa_codigo(row.get("codigo_op")) == codigo
            ),
            None,
        )
        if elegivel is None:
            return _fail(
                "qualidade_op_nao_elegivel",
                "A OP ainda não chegou na operação de inspeção ou já foi concluída.",
            )
        # Digitar a OP não contorna o recorte de setor: quem inspeciona é quem
        # produziu a peça.
        if not self._pertence_ao_setor(elegivel, setor):
            return _fail(
                "qualidade_op_outro_setor",
                f"Esta OP é inspecionada por {_texto(elegivel.get('tipo_setor_origem'))}, não por {setor}.",
            )

        numero_operacao = _texto(operacao.get("numero_operacao"), 20)
        aberta = self.db.buscar_inspecao_aberta(codigo, numero_operacao)
        if aberta is None:
            produto = _texto(
                operacao.get("produto_codigo") or operacao.get("op_produto_codigo"), 60
            )
            template = self.db.buscar_template_qualidade(produto)
            aberta = self.db.abrir_inspecao_qualidade(
                codigo_op=codigo,
                catalogo_operacao_id=operacao.get("id"),
                numero_operacao=numero_operacao,
                produto_codigo=produto,
                produto_descricao=operacao.get("produto_descricao")
                or operacao.get("op_produto_descricao"),
                tipo_setor=QUALITY_APPOINTMENT_SECTOR,
                # ``tipo_setor`` é a faixa de apontamento ("Qualidade"); o dono
                # da inspeção é quem produziu a peça, e é ele que a escrita
                # revalida depois. Gravado aqui porque a fila deixa de listar a
                # OP assim que a inspeção abre.
                tipo_setor_origem=_texto(elegivel.get("tipo_setor_origem"), 60),
                codigo_recurso=_texto(operacao.get("codigo_recurso"), 60),
                quantidade_total=max(1, int(elegivel.get("quantidade") or 1)),
                template_id=(template or {}).get("id"),
                template_revisao=(template or {}).get("revisao"),
                operador=self.operador,
                iniciada_em=self._now(),
            )
            if aberta is None:
                aberta = self.db.buscar_inspecao_aberta(codigo, numero_operacao)
        if aberta is None:
            return _fail(
                "qualidade_inspecao_indisponivel",
                "Não foi possível abrir a inspeção desta OP. Atualize a fila e tente novamente.",
            )

        inicio = self._iniciar_operacao_canonica(operacao, aberta, badges=badges)
        if not inicio.ok:
            return inicio
        return QualityResult(
            True,
            "Inspeção aberta.",
            data=self.obter_inspecao(aberta["id"]),
        )

    def dispensar_inspecao(self, op, setor, *, badges=None, motivo=None):
        """Pula a inspeção pela regra transitória, sem falsificá-la.

        Enquanto os operadores das máquinas são treinados para inspecionar as
        próprias peças, a inspeção **não** é bloqueio obrigatório do fluxo. O
        que o Gestor registra é exatamente isso: a decisão de seguir sem a
        inspeção formal — nunca uma aprovação, cota, peça ou RNC que não
        aconteceram. A operação seguinte é liberada pela mesma regra de sempre.
        """

        codigo = limpa_codigo(op)
        if not codigo:
            return _fail("qualidade_op_obrigatoria", "Informe a OP.")

        crachas = [str(item or "").strip() for item in (badges or ()) if str(item or "").strip()]
        if not crachas:
            return _fail(
                "qualidade_dispensa_cracha_obrigatorio",
                "Informe o crachá de quem autoriza seguir sem a inspeção.",
            )
        finder = getattr(self.db, "buscar_operadores_apontamento", None)
        operadores = list(finder(crachas) or []) if callable(finder) else []
        if not operadores:
            return _fail(
                "qualidade_dispensa_cracha_invalido",
                "Crachá não cadastrado ou inativo.",
            )

        ja_dispensada = None
        leitor = getattr(self.db, "buscar_dispensa_inspecao", None)
        if callable(leitor):
            ja_dispensada = leitor(codigo)
        if ja_dispensada:
            # Idempotente: repetir a decisão não cria uma segunda dispensa.
            return QualityResult(
                True,
                "A inspeção desta OP já havia sido dispensada.",
                code="qualidade_dispensa_existente",
                data={"dispensa": dict(ja_dispensada)},
            )

        elegiveis = list(self.db.listar_ops_elegiveis_inspecao() or ())
        alvo = next(
            (
                dict(row) for row in elegiveis
                if limpa_codigo(row.get("codigo_op")) == codigo
                and self._pertence_ao_setor(row, setor)
            ),
            None,
        )
        if alvo is None:
            return _fail(
                "qualidade_op_nao_elegivel",
                "Esta OP não está aguardando inspeção.",
            )
        if alvo.get("inspecao_id"):
            return _fail(
                "qualidade_inspecao_em_andamento",
                "A inspeção desta OP já foi iniciada. Conclua-a pela tela da Qualidade.",
            )

        autor = str(operadores[0].get("nome") or crachas[0]).strip()
        registro = getattr(self.db, "dispensar_inspecao_qualidade", None)
        if not callable(registro):
            return _fail(
                "qualidade_dispensa_indisponivel",
                "O registro de dispensa não está disponível neste ambiente.",
            )
        dispensa = registro(
            codigo_op=codigo,
            catalogo_operacao_id=alvo.get("catalogo_operacao_id"),
            numero_operacao=alvo.get("numero_operacao"),
            produto_codigo=alvo.get("produto_codigo"),
            produto_descricao=alvo.get("produto_descricao"),
            tipo_setor=setor or QUALITY_APPOINTMENT_SECTOR,
            tipo_setor_origem=_texto(alvo.get("tipo_setor_origem"), 60),
            codigo_recurso=alvo.get("codigo_recurso"),
            quantidade_total=alvo.get("quantidade") or 1,
            operador=self.operador,
            motivo=motivo,
            autorizada_por=autor,
            cracha=crachas[0],
            dispensada_em=self._now(),
        )
        if dispensa is None:
            return _fail(
                "qualidade_dispensa_conflito",
                "A situação da inspeção mudou. Atualize a fila.",
            )
        self._registrar_evento_dispensa(codigo, alvo, autor, crachas[0], motivo)
        return QualityResult(
            True,
            "Inspeção dispensada. A OP segue para a próxima etapa.",
            code="qualidade_inspecao_dispensada",
            data={"dispensa": dict(dispensa)},
        )

    def _registrar_evento_dispensa(self, codigo_op, alvo, autor, cracha, motivo):
        """Trilha de auditoria da decisão, fora do domínio da inspeção."""

        registrar = getattr(self.db, "registrar_evento_sistema", None)
        if not callable(registrar):
            return
        try:
            registrar(
                tipo="qualidade_inspecao_dispensada",
                origem="QualityService",
                referencia=codigo_op,
                mensagem="Inspeção dispensada pela regra transitória de implantação.",
                operador=self.operador,
                detalhes=json.dumps(
                    {
                        "codigo_op": codigo_op,
                        "numero_operacao": alvo.get("numero_operacao"),
                        "catalogo_operacao_id": alvo.get("catalogo_operacao_id"),
                        "autorizada_por": autor,
                        "cracha": cracha,
                        "motivo": motivo,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                data_hora=self._now(),
            )
        except Exception:  # pragma: no cover - auditoria não bloqueia o fluxo
            logging.exception("Falha ao registrar a dispensa de inspeção.")

    def _apontamento_ativo(self, codigo_op, recurso):
        """Execução da operação INSPECAO ainda aberta, se houver.

        Uma inspeção que terminou com retrabalho deixa a operação parcialmente
        finalizada e ainda ativa. A sessão seguinte continua nesse mesmo
        apontamento em vez de abrir um segundo — a operação do roteiro é uma só.
        """

        rows = self.db.listar_apontamentos_operacionais(
            QUALITY_APPOINTMENT_SECTOR, maquina=recurso, somente_ativos=True
        )
        return next(
            (
                dict(row)
                for row in rows
                if limpa_codigo(row.get("op")) == limpa_codigo(codigo_op)
            ),
            None,
        )

    def _iniciar_operacao_canonica(self, operacao, inspecao, *, badges=None):
        """Coloca a operação INSPECAO em execução usando o fluxo já homologado.

        Não existe caminho paralelo: é o mesmo ``OperatorFlowService`` do posto,
        e é ele que grava o evento canônico e, quando a outbox está habilitada,
        a obrigação outbound correspondente.

        Um apontamento já existente só dispensa o ``Início`` quando de fato
        está em execução. Uma inspeção parcial devolve a operação à fila, e
        reaproveitar esse apontamento parado como se estivesse rodando deixava
        a reinspeção sem saída: o fechamento tentaria fila → finalizado, que a
        máquina de estados canônica proíbe. Quem decide é o estado, não a
        simples existência da linha.
        """

        if inspecao.get("apontamento_id"):
            return QualityResult(True, "Operação de inspeção já iniciada.")
        recurso = _texto(operacao.get("codigo_recurso"), 60)
        ativo = self._apontamento_ativo(inspecao["codigo_op"], recurso)
        if (
            ativo is not None
            and operator_state_from_status(ativo.get("status")) is not OperatorState.QUEUED
        ):
            self.db.vincular_apontamento_inspecao(inspecao["id"], ativo["id"])
            return QualityResult(True, "Operação de inspeção em execução.", data=ativo)
        # Fila: o próprio fluxo canônico reabre este mesmo apontamento, sem
        # criar um segundo para a mesma operação do roteiro.
        fluxo = OperatorFlowService(self.db, self.operador, now_func=self._now)
        resultado = fluxo.executar(
            "Início",
            op=inspecao["codigo_op"],
            setor=QUALITY_APPOINTMENT_SECTOR,
            recurso=recurso,
            operacao=dict(operacao),
            operadores_cracha=badges,
        )
        if not resultado.ok:
            return _fail(
                resultado.code or "qualidade_inicio_recusado",
                resultado.message,
                resultado.data,
            )
        apontamento_id = (resultado.data or {}).get("id")
        if apontamento_id:
            self.db.vincular_apontamento_inspecao(inspecao["id"], apontamento_id)
        return QualityResult(True, resultado.message, data=resultado.data)

    # ------------------------------------------------------------------
    # Estado da inspeção
    # ------------------------------------------------------------------
    def obter_inspecao(self, inspecao_id):
        """Estado completo da tela de apontamento, já resolvido pelo backend."""

        sessao = self.db.buscar_inspecao_qualidade(inspecao_id)
        if sessao is None or self._exigir_setor(sessao) is not None:
            # Inspeção de outro setor não existe para este operador: devolver
            # ``None`` mantém o 404 do roteador e não confirma o id sondado.
            return None
        pecas = [dict(row) for row in (self.db.listar_pecas_inspecionadas(sessao["id"]) or ())]
        registradas = len(pecas)
        total = int(sessao.get("quantidade_total") or 0)
        template = self.db.buscar_template_qualidade(sessao.get("produto_codigo"))
        desenho = self.db.buscar_desenho_produto(sessao.get("produto_codigo"))
        proxima = registradas + 1 if registradas < total else None
        return {
            "id": sessao["id"],
            "op": sessao.get("codigo_op"),
            "operacao": sessao.get("numero_operacao"),
            "produto": sessao.get("produto_codigo"),
            "produto_descricao": sessao.get("produto_descricao"),
            "recurso": sessao.get("codigo_recurso"),
            "quantidade_total": total,
            "pecas_registradas": registradas,
            "peca_atual": proxima,
            "ultima_peca": bool(proxima is not None and proxima >= total),
            "status": sessao.get("status"),
            "operador": sessao.get("operador"),
            "template": template_publico(template),
            "template_editavel": bool(template is None),
            "desenho": desenho_publico(desenho),
            "pecas": [
                {
                    "numero_peca": int(item.get("numero_peca") or 0),
                    "resultado": item.get("resultado"),
                    "rnc": item.get("rnc_codigo"),
                    "operador": item.get("operador"),
                    "registrada_em": item.get("registrada_em"),
                }
                for item in pecas
            ],
        }

    # ------------------------------------------------------------------
    # Template de cotas
    # ------------------------------------------------------------------
    def definir_template(self, produto_codigo, cotas, *, pode_editar=False, produto_descricao=None):
        """Cria a primeira definição ou aplica uma edição de Supervisor/Líder."""

        produto = _texto(produto_codigo, 60)
        if not produto:
            return _fail("qualidade_produto_obrigatorio", "Produto não identificado.")
        existente = self.db.buscar_template_qualidade(produto)
        if existente is not None and not pode_editar:
            # Depois de salvo, o template é padrão do produto. Alterá-lo mudaria
            # o critério de aceitação da peça, então a permissão é validada aqui
            # e não apenas escondendo o botão no React.
            return _fail(
                "qualidade_template_protegido",
                "As cotas padrão deste produto já estão cadastradas. "
                "Somente Supervisor ou Líder pode alterá-las.",
            )
        normalizadas, erro = self._normalizar_cotas_template(cotas)
        if erro is not None:
            return erro
        template = self.db.salvar_template_qualidade(
            produto,
            normalizadas,
            produto_descricao=produto_descricao,
            usuario_id=self.usuario_id,
            usuario_nome=self.operador,
            agora=self._now(),
            nova_revisao=existente is not None,
        )
        return QualityResult(
            True,
            "Cotas padrão salvas para o produto." if existente is None
            else "Cotas padrão atualizadas.",
            data=template_publico(template),
        )

    @staticmethod
    def _normalizar_cotas_template(cotas):
        itens = list(cotas or ())
        if not itens:
            return None, _fail(
                "qualidade_cotas_obrigatorias",
                "Informe ao menos a Cota 1 com o padrão da peça.",
            )
        normalizadas = []
        sequencias = set()
        for ordem, cota in enumerate(itens, start=1):
            dados = dict(cota or {})
            sequencia = int(dados.get("sequencia") or ordem)
            if sequencia < 1:
                return None, _fail(
                    "qualidade_cota_sequencia_invalida",
                    "A sequência da cota deve começar em 1.",
                )
            if sequencia in sequencias:
                return None, _fail(
                    "qualidade_cota_duplicada",
                    f"A Cota {sequencia} foi informada mais de uma vez.",
                )
            sequencias.add(sequencia)
            padrao = _texto(dados.get("padrao"))
            if not padrao:
                return None, _fail(
                    "qualidade_cota_padrao_obrigatorio",
                    f"Informe o padrão da Cota {sequencia}.",
                )
            normalizadas.append(
                {
                    "sequencia": sequencia,
                    "descricao": _texto(dados.get("descricao"), 200) or None,
                    "padrao": padrao,
                    # A experiência operacional usa milímetros como unidade
                    # fixa. A coluna permanece no schema para preservar o
                    # histórico, mas nenhum cliente escolhe outra semântica.
                    "unidade": "mm",
                }
            )
        normalizadas.sort(key=lambda item: item["sequencia"])
        return normalizadas, None

    # ------------------------------------------------------------------
    # Peça inspecionada
    # ------------------------------------------------------------------
    def registrar_peca(
        self,
        inspecao_id,
        *,
        numero_peca,
        resultado,
        medidas,
        rnc=None,
        badges=None,
    ):
        """Valida e grava uma unidade; avança a inspeção ou a finaliza."""

        sessao = self.db.buscar_inspecao_qualidade(inspecao_id)
        if sessao is None:
            return _fail("qualidade_inspecao_inexistente", "Inspeção não encontrada.")
        recusa = self._exigir_setor(sessao)
        if recusa is not None:
            return recusa
        if sessao.get("status") != "EM_INSPECAO":
            return _fail(
                "qualidade_inspecao_concluida",
                "Esta inspeção já foi concluída.",
            )
        registradas = len(self.db.listar_pecas_inspecionadas(sessao["id"]) or ())
        total = int(sessao.get("quantidade_total") or 0)
        esperada = registradas + 1
        if registradas >= total:
            return _fail(
                "qualidade_inspecao_completa",
                "Todas as peças desta OP já foram inspecionadas.",
            )
        if int(numero_peca or 0) != esperada:
            return _fail(
                "qualidade_sequencia_peca",
                f"A próxima unidade a inspecionar é a peça {esperada} de {total}.",
                {"peca_atual": esperada, "quantidade_total": total},
            )

        template = self.db.buscar_template_qualidade(sessao.get("produto_codigo"))
        if not template or not template.get("cotas"):
            return _fail(
                "qualidade_template_ausente",
                "Cadastre as cotas padrão do produto antes de inspecionar.",
            )
        cotas, erro = self._resolver_medidas(template["cotas"], medidas)
        if erro is not None:
            return erro

        decisao = normalize_piece_result(resultado)
        if not decisao:
            return _fail(
                "qualidade_resultado_invalido",
                "Selecione Aprovada, Retrabalho ou Refugo.",
            )
        nao_conforme = any(
            cota["status"] == QUALITY_MEASURE_NON_CONFORMING for cota in cotas
        )
        if nao_conforme and decisao == QUALITY_RESULT_APPROVED:
            return _fail(
                "qualidade_aprovacao_nao_conforme",
                "A peça possui cota não conforme e não pode ser Aprovada.",
            )
        dados_rnc = None
        if nao_conforme:
            motivo = _texto((rnc or {}).get("motivo"), 500)
            if len(motivo) < 3:
                return _fail(
                    "qualidade_rnc_obrigatoria",
                    "Abra a RNC e descreva a não conformidade antes de salvar a peça.",
                )
            dados_rnc = {
                "codigo": f"RNC-{sessao['id']}-{esperada:04d}",
                "motivo": motivo,
                "observacao": _texto((rnc or {}).get("observacao"), 500) or None,
            }
        elif rnc:
            return _fail(
                "qualidade_rnc_sem_nao_conformidade",
                "Não existe cota não conforme nesta peça; a RNC não se aplica.",
            )

        operacao_retrabalho = None
        if decisao == QUALITY_RESULT_REWORK:
            operacao_inspecao = self.db.buscar_operacao_inspecao(sessao["codigo_op"])
            finder = getattr(self.db, "buscar_operacao_produtiva_anterior", None)
            if operacao_inspecao is not None and callable(finder):
                operacao_retrabalho = finder(
                    sessao["codigo_op"], operacao_inspecao.get("ordem")
                )
            if operacao_retrabalho is None:
                return _fail(
                    "qualidade_retrabalho_sem_operacao_anterior",
                    "O roteiro não possui uma operação produtiva anterior cadastrada para receber o retrabalho.",
                )

        # A última peça fecha a operação, e fechar exige crachá. A validação vem
        # antes da gravação para que a peça não fique registrada com a inspeção
        # travada por falta de um dado que a tela poderia ter pedido.
        if esperada >= total and not [
            item for item in (badges or ()) if str(item or "").strip()
        ]:
            return _fail(
                "qualidade_cracha_obrigatorio",
                "Informe ao menos um crachá de operador para finalizar a inspeção.",
                {"peca_atual": esperada, "quantidade_total": total},
            )

        peca = self.db.registrar_peca_inspecionada(
            sessao["id"],
            numero_peca=esperada,
            resultado=decisao,
            possui_nao_conformidade=nao_conforme,
            operador=self.operador,
            cotas=cotas,
            rnc=dados_rnc,
            operacao_retrabalho=operacao_retrabalho,
            registrada_em=self._now(),
        )
        if peca is None:
            return _fail(
                "qualidade_peca_duplicada",
                f"A peça {esperada} de {total} já foi registrada por outro apontamento.",
            )

        if esperada < total:
            confirmacao = {
                QUALITY_RESULT_APPROVED: "Peça aprovada com sucesso.",
                QUALITY_RESULT_REWORK: "Peça enviada para retrabalho.",
                QUALITY_RESULT_SCRAP: "Refugo registrado.",
            }[decisao]
            return QualityResult(
                True,
                f"{confirmacao} Próxima: peça {esperada + 1} de {total}.",
                data=self.obter_inspecao(sessao["id"]),
            )
        return self._finalizar(sessao, badges=badges)

    def _resolver_medidas(self, cotas_template, medidas):
        """Casa cada cota do template com a medida informada, sem curinga.

        Wave 5.1 — a conformidade é conta do backend, não escolha do operador.
        A conta vive em ``mes/domain/quality_measures.py`` e é compartilhada com
        o portão da primeira peça: aqui ela apenas vira ``QualityResult``.
        """

        resolvidas, erro = resolve_checklist_measures(cotas_template, medidas)
        if erro is not None:
            return None, _fail(erro.code, erro.message)
        return resolvidas, None

    # ------------------------------------------------------------------
    # Conclusão
    # ------------------------------------------------------------------
    def _finalizar(self, sessao, *, badges=None):
        """Fecha a operação INSPECAO pelo fluxo canônico e conclui a sessão."""

        pecas = [dict(item) for item in (self.db.listar_pecas_inspecionadas(sessao["id"]) or ())]
        aprovadas = sum(1 for item in pecas if item.get("resultado") == QUALITY_RESULT_APPROVED)
        refugos = sum(1 for item in pecas if item.get("resultado") == QUALITY_RESULT_SCRAP)
        retrabalhos = sum(1 for item in pecas if item.get("resultado") == QUALITY_RESULT_REWORK)
        crachas = [str(item or "").strip() for item in (badges or ()) if str(item or "").strip()]
        if not crachas:
            return _fail(
                "qualidade_cracha_obrigatorio",
                "Informe ao menos um crachá de operador para finalizar a inspeção.",
                {"aprovadas": aprovadas, "retrabalho": retrabalhos, "refugo": refugos},
            )
        operacao = self.db.buscar_operacao_inspecao(sessao["codigo_op"])
        if operacao is None:
            return _fail(
                "qualidade_operacao_inexistente",
                "A operação de inspeção não está mais disponível no roteiro desta OP.",
            )
        fluxo = OperatorFlowService(self.db, self.operador, now_func=self._now)
        resultado = fluxo.executar(
            "Finalizado",
            op=sessao["codigo_op"],
            setor=QUALITY_APPOINTMENT_SECTOR,
            recurso=_texto(operacao.get("codigo_recurso"), 60),
            operacao=dict(operacao),
            pecas_boas=aprovadas,
            refugo=refugos,
            retrabalho_quantidade=retrabalhos,
            operadores_cracha=crachas,
        )
        if not resultado.ok:
            return _fail(
                resultado.code or "qualidade_fechamento_recusado",
                resultado.message,
                resultado.data,
            )
        self.db.concluir_inspecao_qualidade(sessao["id"], finalizada_em=self._now())
        # Retrabalho não completa a quantidade planejada: nesse caso a operação
        # de inspeção fica parcialmente finalizada, com saldo, e a OP volta para
        # a fila quando as peças retrabalhadas forem reapresentadas. Essa é a
        # regra canônica de saldo do Gestor, aplicada sem exceção à Qualidade.
        parcial = bool((resultado.data or {}).get("finalizacao_parcial"))
        saldo = int((resultado.data or {}).get("saldo_restante") or 0)
        resumo = (
            f"{aprovadas} aprovada(s), {retrabalhos} retrabalho e {refugos} refugo"
        )
        mensagem = (
            f"Inspeção concluída: {resumo}. A operação permanece aberta com "
            f"saldo de {saldo} peça(s) para reinspeção."
            if parcial
            else f"Inspeção concluída: {resumo}."
        )
        return QualityResult(
            True,
            mensagem,
            "inspecao_concluida",
            {
                "inspecao_id": sessao["id"],
                "op": sessao["codigo_op"],
                "aprovadas": aprovadas,
                "retrabalho": retrabalhos,
                "refugo": refugos,
                "operacao_finalizada": not parcial,
                "saldo_restante": saldo,
                "apontamento": resultado.data,
            },
        )

    def finalizar_inspecao(self, inspecao_id, *, badges=None):
        """Fecha uma inspeção cuja última peça já foi registrada."""

        sessao = self.db.buscar_inspecao_qualidade(inspecao_id)
        if sessao is None:
            return _fail("qualidade_inspecao_inexistente", "Inspeção não encontrada.")
        recusa = self._exigir_setor(sessao)
        if recusa is not None:
            return recusa
        if sessao.get("status") != "EM_INSPECAO":
            return _fail("qualidade_inspecao_concluida", "Esta inspeção já foi concluída.")
        registradas = len(self.db.listar_pecas_inspecionadas(sessao["id"]) or ())
        if registradas < int(sessao.get("quantidade_total") or 0):
            return _fail(
                "qualidade_inspecao_incompleta",
                "Ainda existem peças pendentes de inspeção nesta OP.",
            )
        return self._finalizar(sessao, badges=badges)

    # ------------------------------------------------------------------
    # Histórico
    # ------------------------------------------------------------------
    def listar_historico(self, setor, **filtros):
        if not sector_has_quality(setor):
            return []
        rows = self.db.listar_historico_qualidade(
            setor=QUALITY_APPOINTMENT_SECTOR, setor_origem=setor, **filtros
        )
        return [
            {
                "peca_id": row.get("peca_id"),
                "inspecao_id": row.get("inspecao_id"),
                "data": row.get("registrada_em"),
                "op": row.get("codigo_op"),
                "operacao": row.get("numero_operacao"),
                "produto": row.get("produto_codigo"),
                "descricao": row.get("produto_descricao"),
                "peca": f"{int(row.get('numero_peca') or 0)}/{int(row.get('quantidade_total') or 0)}",
                "numero_peca": int(row.get("numero_peca") or 0),
                "recurso": row.get("codigo_recurso"),
                "operador": row.get("operador"),
                "resultado": row.get("resultado"),
                "rnc": row.get("rnc_codigo"),
                "rnc_motivo": row.get("rnc_motivo"),
            }
            for row in (rows or ())
        ]

    def detalhar_peca(self, peca_id):
        """Rastreabilidade de uma unidade: cotas, padrões usados e medidas.

        Revalida o setor dono da inspeção antes de devolver as medidas —
        mesma fronteira de ``_exigir_setor``, para que trocar o id na URL não
        vaze a rastreabilidade de uma peça de outro setor.
        """

        sessao = self.db.buscar_inspecao_da_peca(peca_id)
        if sessao is None or self._exigir_setor(sessao) is not None:
            return None
        cotas = [dict(row) for row in (self.db.listar_resultados_cota(peca_id) or ())]
        detalhes = []
        for cota in cotas:
            # O snapshot do padrão é o critério que valia na hora da inspeção;
            # os limites são recompostos dele, nunca do template atual.
            avaliacao = evaluate_measure(
                cota.get("medida"), cota.get("padrao_snapshot")
            ).as_public()
            detalhes.append({
                "sequencia": int(cota.get("sequencia") or 0),
                "descricao": cota.get("descricao_snapshot"),
                "padrao": cota.get("padrao_snapshot"),
                "unidade": cota.get("unidade_snapshot"),
                "medida": cota.get("medida"),
                "status": cota.get("status"),
                "referencia": avaliacao["referencia"],
                "margem": avaliacao["margem"],
                "limite_inferior": avaliacao["limite_inferior"],
                "limite_superior": avaliacao["limite_superior"],
            })
        return detalhes
