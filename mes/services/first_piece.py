"""Caso de uso da **primeira peça** — o portão de liberação do lote (Wave 5).

Regra funcional em uma frase: a operação só pode ser finalizada depois que a
primeira peça foi produzida, o Setup foi apontado onde ele existe, o operador
inspecionou essa peça e o resultado foi ``CONFORME``.

Três fronteiras importam:

* **Quem inspeciona é o operador do posto.** Esta inspeção não é a inspeção
  dimensional da operação ``INSPECAO`` do roteiro (``mes/services/quality.py``)
  e não exige setor de Qualidade habilitado. São dois domínios distintos e
  ambos continuam existindo.
* **Uma peça, um lote.** A aprovação vale para a OP inteira, inclusive quando o
  planejado é 1. Nenhuma inspeção individual por unidade é criada.
* **Retrabalho da primeira peça bloqueia a OP; refugo não.** As duas decisões,
  porém, exigem o crachá de um responsável **designado**
  (``autorizador_retrabalho``): o retrabalho é desbloqueado por ele e o refugo é
  autorizado por ele antes do descarte. Vale o cadastro de crachás que já
  existe — sem login e sem autenticação paralela.
"""

from __future__ import annotations

from contextlib import nullcontext
from dataclasses import dataclass
from datetime import datetime
import logging

from app.core.normalization import limpa_codigo
from app.core.quality import QUALITY_MEASURE_NON_CONFORMING
from mes.domain.first_piece import (
    FIRST_PIECE_BLOCK_OCCURRENCE,
    FIRST_PIECE_CONFORMING,
    FIRST_PIECE_PENDING,
    FIRST_PIECE_PRODUCED,
    FIRST_PIECE_REWORK,
    FIRST_PIECE_SCRAP,
    FIRST_PIECE_SCRAP_OCCURRENCE,
    FirstPieceGate,
    evaluate_first_piece_gate,
    first_piece_applies,
    first_piece_gate_is_structured,
    normalize_first_piece_result,
    sector_has_setup,
)
from mes.domain.quality_measures import (
    resolve_checklist_measures,
    template_publico,
)
from mes.services.internal_alerts import InternalAlertService


@dataclass(frozen=True)
class FirstPieceResult:
    ok: bool
    message: str
    code: str = ""
    data: dict | None = None


#: Teto da observação da inspeção (coluna TEXT). Espelha o do repositório: o
#: snapshot de revisão/padrão das cotas não pode ser cortado em silêncio.
OBSERVACAO_INSPECAO_LIMITE = 2000


def _fail(code, message, data=None):
    return FirstPieceResult(False, message, code, data)


def _operation_id(operacao):
    row = dict(operacao or {})
    return row.get("id") or row.get("catalogo_operacao_id")


def _texto(valor, limite=200):
    return str(valor or "").strip()[:limite]


class FirstPieceService:
    """Orquestra o ciclo da primeira peça sem acoplar regra ao frontend."""

    def __init__(self, db, operador="Operador", *, now_func=None):
        self.db = db
        self.operador = str(operador or "Operador").strip() or "Operador"
        self._now = now_func or (lambda: datetime.now().replace(microsecond=0))
        self._alertas = InternalAlertService(db, self.operador, now_func=self._now)

    # ------------------------------------------------------------------
    # Configuração
    # ------------------------------------------------------------------
    def setup_obrigatorio(self, setor) -> bool:
        """Setup é obrigatório só onde ele já existe como configuração.

        A autoridade é a mesma de sempre: o setor precisa possuir Setup (Solda e
        Pintura não possuem) **e** o catálogo de status precisa ter um motivo de
        Setup cadastrado. Nada é inventado para cumprir a regra da primeira peça.
        """

        if not sector_has_setup(setor):
            return False
        loader = getattr(self.db, "listar_status_recursos", None)
        if not callable(loader):
            return False
        try:
            return bool(list(loader(setup=True) or ()))
        except Exception:  # pragma: no cover - catálogo indisponível
            logging.exception("Falha ao ler o catálogo de status de Setup.")
            return False

    # ------------------------------------------------------------------
    # Ciclo de vida
    # ------------------------------------------------------------------
    def garantir(self, *, op, setor, recurso, operacao, apontamento_id=None):
        """Cria a primeira peça da operação quando ela ainda não existe."""

        if not first_piece_applies(setor, operacao):
            return None
        criar = getattr(self.db, "garantir_primeira_peca", None)
        if not callable(criar):
            return None
        dados = dict(operacao or {})
        try:
            return criar(
                codigo_op=limpa_codigo(op),
                catalogo_operacao_id=_operation_id(dados),
                numero_operacao=dados.get("numero_operacao") or dados.get("codigo"),
                apontamento_id=apontamento_id,
                produto_codigo=dados.get("produto_codigo"),
                produto_descricao=dados.get("produto_descricao"),
                tipo_setor=setor,
                codigo_recurso=dados.get("codigo_recurso") or dados.get("recurso"),
                recurso_apontado=recurso,
                quantidade_planejada=dados.get("quantidade_planejada")
                or dados.get("quantidade")
                or 1,
                setup_obrigatorio=self.setup_obrigatorio(setor),
                criada_em=self._now(),
            )
        except Exception:  # pragma: no cover - não pode derrubar o apontamento
            logging.exception("Falha ao garantir a primeira peça da OP %s.", op)
            return None

    def marcar_setup(self, *, op, operacao):
        """Anota o Setup já aceito pelo fluxo canônico do operador."""

        marcar = getattr(self.db, "registrar_setup_primeira_peca", None)
        if not callable(marcar):
            return None
        try:
            return marcar(
                limpa_codigo(op),
                _operation_id(operacao),
                instante=self._now(),
            )
        except Exception:  # pragma: no cover
            logging.exception("Falha ao anotar o Setup da primeira peça da OP %s.", op)
            return None

    # ------------------------------------------------------------------
    # Leitura
    # ------------------------------------------------------------------
    def estado(self, *, op, setor, recurso=None, operacao=None):
        """Estado completo da primeira peça, já resolvido para a tela."""

        aplicavel = first_piece_applies(setor, operacao)
        if not aplicavel:
            gate = evaluate_first_piece_gate(aplicavel=False)
            return {**gate.como_dicionario(), "registro": None, "checklist": None}
        linha = self._linha(op, operacao)
        gate = self._avaliar(linha, setor, operacao)
        return {
            **gate.como_dicionario(),
            # Toda medição gravada (conforme ou NC). A tela devolve este número
            # ao medir e o banco recusa o 2º envio da mesma peça.
            "pecas_registradas": int((linha or {}).get("inspecao_pecas_registradas") or 0),
            # N que a inspeção vai pedir, já antes da 1ª medição (que é quando
            # ele é fixado): a tela mostra "0/5" desde o cadastro das cotas.
            "pecas_previstas": self._pecas_previstas(linha, setor, operacao),
            "registro": self._publico(linha),
            "checklist": self.checklist(setor=setor, operacao=operacao, registro=linha),
        }

    def _pecas_previstas(self, linha, setor, operacao):
        if not first_piece_gate_is_structured(setor, operacao):
            return 0
        prever = getattr(self.db, "prever_pecas_exigidas_inspecao", None)
        if not callable(prever):
            return 0
        dados = dict(operacao or {})
        base = dict(linha or {}) or {
            "produto_codigo": dados.get("produto_codigo"),
            "numero_operacao": dados.get("numero_operacao") or dados.get("codigo"),
            "quantidade_planejada": dados.get("quantidade_planejada") or dados.get("quantidade"),
        }
        return int(prever(base) or 0)

    def checklist(self, *, setor, operacao, registro=None):
        """Checklist de cotas do produto, quando o portão é o estruturado.

        Nenhum cadastro novo é criado: as cotas são o mesmo template do produto
        usado pela inspeção dimensional (``qualidade_templates``). Quando ele
        ainda não existe, o portão devolve ``configuravel`` e a tela usa o
        editor que já existe na Qualidade.
        """

        if not first_piece_gate_is_structured(setor, operacao):
            return None
        produto = self._produto(operacao, registro)
        template = None
        loader = getattr(self.db, "buscar_template_qualidade", None)
        if produto and callable(loader):
            try:
                template = loader(produto)
            except Exception:  # pragma: no cover - catálogo indisponível
                logging.exception("Falha ao ler o checklist do produto %s.", produto)
        publico = template_publico(template)
        return {
            "produto": produto,
            "produto_descricao": dict(operacao or {}).get("produto_descricao"),
            "template": publico,
            "configuravel": not (publico and publico.get("cotas")),
        }

    def avaliar_finalizacao(self, *, op, setor, operacao) -> FirstPieceGate:
        """Portão consultado pelo ``OperatorFlowService`` antes de finalizar."""

        if not first_piece_applies(setor, operacao):
            return evaluate_first_piece_gate(aplicavel=False)
        return self._avaliar(self._linha(op, operacao), setor, operacao)

    def bloqueio_ativo(self, *, op, setor, operacao) -> dict | None:
        """Bloqueio de retrabalho da primeira peça, se existir."""

        if not first_piece_applies(setor, operacao):
            return None
        linha = self._linha(op, operacao)
        return dict(linha) if linha and linha.get("bloqueio_ativo") else None

    # ------------------------------------------------------------------
    # Ações do operador
    # ------------------------------------------------------------------
    def registrar_producao(self, *, op, setor, recurso, operacao, apontamento_id=None):
        """O operador declara que a primeira peça saiu da máquina."""

        if not first_piece_applies(setor, operacao):
            return _fail(
                "primeira_peca_nao_aplicavel",
                "Esta operação não está sujeita à regra da primeira peça.",
            )
        linha = self._linha(op, operacao) or self.garantir(
            op=op,
            setor=setor,
            recurso=recurso,
            operacao=operacao,
            apontamento_id=apontamento_id,
        )
        if linha is None:
            return _fail(
                "primeira_peca_indisponivel",
                "Não foi possível abrir a primeira peça desta operação.",
            )
        if linha.get("bloqueio_ativo"):
            return _fail(
                "primeira_peca_bloqueada",
                "A OP está bloqueada pelo retrabalho da primeira peça. "
                "Chame o responsável para liberar com o crachá dele.",
                self._publico(linha),
            )
        if linha.get("status") == FIRST_PIECE_CONFORMING:
            return FirstPieceResult(
                True,
                "A primeira peça desta operação já foi aprovada.",
                "primeira_peca_ja_aprovada",
                self._publico(linha),
            )
        atualizada = self.db.registrar_primeira_peca_produzida(
            linha["id"],
            operador=self.operador,
            apontamento_id=apontamento_id,
            instante=self._now(),
        )
        if atualizada is None:
            return _fail(
                "primeira_peca_estado_alterado",
                "A situação da primeira peça mudou. Atualize o posto e tente novamente.",
            )
        gate = self._avaliar(atualizada, setor, operacao)
        return FirstPieceResult(
            True,
            "Primeira peça registrada. Inspecione-a para liberar o lote."
            if not gate.liberado
            else "Primeira peça registrada.",
            "primeira_peca_produzida",
            {**gate.como_dicionario(), "registro": self._publico(atualizada)},
        )

    def inspecionar(
        self, *, op, setor, recurso, operacao, resultado, observacao=None
    ):
        """Registra a decisão do operador sobre a primeira peça."""

        if not first_piece_applies(setor, operacao):
            return _fail(
                "primeira_peca_nao_aplicavel",
                "Esta operação não está sujeita à regra da primeira peça.",
            )
        decisao = normalize_first_piece_result(resultado)
        if not decisao:
            return _fail(
                "primeira_peca_resultado_invalido",
                "Selecione Conforme, Retrabalho ou Refugo.",
            )
        linha = self._linha(op, operacao)
        if linha is None:
            return _fail(
                "primeira_peca_inexistente",
                "Registre a primeira peça produzida antes de inspecioná-la.",
            )
        if linha.get("bloqueio_ativo"):
            return _fail(
                "primeira_peca_bloqueada",
                "A OP está bloqueada pelo retrabalho da primeira peça. "
                "Chame o responsável para liberar com o crachá dele.",
                self._publico(linha),
            )
        if not linha.get("peca_produzida_em"):
            return _fail(
                "primeira_peca_nao_produzida",
                "Registre a primeira peça produzida antes de inspecioná-la.",
                self._publico(linha),
            )
        if decisao == FIRST_PIECE_CONFORMING and linha.get("setup_obrigatorio") and not linha.get(
            "setup_registrado_em"
        ):
            # Aprovar antes do Setup transformaria o portão em formalidade: a
            # peça aprovada teria saído de uma máquina ainda não preparada.
            return _fail(
                "primeira_peca_setup_pendente",
                "Aponte o Setup desta operação antes de aprovar a primeira peça.",
                self._publico(linha),
            )
        if decisao == FIRST_PIECE_SCRAP and not linha.get("apontamento_id"):
            return _fail(
                "primeira_peca_apontamento_pendente",
                "Inicie a operação antes de registrar o refugo da primeira peça.",
                self._publico(linha),
            )

        if decisao == FIRST_PIECE_CONFORMING and first_piece_gate_is_structured(setor, operacao):
            # N fica fixado ANTES da aprovação, em qualquer caminho (checklist
            # ou ação "inspecionar"): não existe o instante "1ª peça aprovada
            # com N vazio", em que o Finalizar entenderia a inspeção como
            # completa e fecharia a OP sem as N peças.
            fixar = getattr(self.db, "fixar_pecas_exigidas_inspecao", None)
            if callable(fixar):
                fixar(linha["id"])

        atualizada = self.db.registrar_inspecao_primeira_peca(
            linha["id"],
            resultado=decisao,
            operador=self.operador,
            observacao=observacao,
            instante=self._now(),
            # Patch 09/11/2026: o retrabalho não trava mais por crachá. O
            # operador retrabalha e mede de novo; o lote só libera com a medida
            # conforme e a não conformidade vai para a Decisão de RNC.
            bloquear=False,
        )
        if atualizada is None:
            return _fail(
                "primeira_peca_estado_alterado",
                "A situação da primeira peça mudou. Atualize o posto e tente novamente.",
            )
        # Histórico de aprovações/reprovações para o log de produção: uma nova
        # medida sobrescreve o resultado na tabela da primeira peça.
        auditar = getattr(self.db, "registrar_auditoria", None)
        if callable(auditar):
            auditar(
                entidade="primeira_peca",
                chave=atualizada.get("codigo_op") or linha.get("codigo_op") or "",
                acao="criar",
                usuario_nome=self.operador,
                depois={
                    "primeira_peca_id": atualizada.get("id"),
                    "codigo_op": atualizada.get("codigo_op"),
                    "numero_operacao": atualizada.get("numero_operacao"),
                    "apontamento_id": atualizada.get("apontamento_id"),
                    "resultado": decisao,
                    "observacao": atualizada.get("observacao"),
                },
            )
        contexto = self._contexto(atualizada)
        if decisao == FIRST_PIECE_REWORK:
            self._alertas.primeira_peca_em_retrabalho(contexto)
            mensagem = (
                "Primeira peça em retrabalho. Retrabalhe a peça e meça de novo; "
                "o lote só libera com a medida conforme."
            )
            codigo = "primeira_peca_retrabalho"
        elif decisao == FIRST_PIECE_SCRAP:
            self._alertas.primeira_peca_refugada(contexto)
            mensagem = (
                "Primeira peça refugada. Produza e inspecione outra primeira peça; "
                "o refugo consome o saldo planejado."
            )
            codigo = "primeira_peca_refugo"
        gate = self._avaliar(atualizada, setor, operacao)
        if decisao not in (FIRST_PIECE_REWORK, FIRST_PIECE_SCRAP):
            codigo = "primeira_peca_conforme"
            # Na Caldeiraria ainda faltam as N peças da inspeção progressiva.
            mensagem = (
                "Primeira peça conforme. O lote está liberado."
                if gate.liberado
                else f"Primeira peça conforme. {gate.message}"
            )
        return FirstPieceResult(
            True,
            mensagem,
            codigo,
            {**gate.como_dicionario(), "registro": self._publico(atualizada)},
        )

    def registrar_checklist(
        self,
        *,
        op,
        setor,
        recurso,
        operacao,
        medidas,
        destino=None,
        cracha_responsavel=None,
        observacao=None,
        apontamento_id=None,
        pecas_registradas=None,
    ):
        """Portão Setup/Qualidade do botão Iniciar (Wave 6B).

        É uma composição dos passos que já existiam — abrir a primeira peça,
        declarar a peça produzida e inspecioná-la — para que o operador execute
        o portão inteiro em uma submissão. Nenhum estado novo é persistido e
        nenhuma regra é reescrita aqui:

        * o Setup continua sendo o **apontamento de estado** do botão Setup, e
          é ele que grava ``setup_registrado_em``. O popup não tem uma segunda
          confirmação de Setup: ele apenas recusa a liberação enquanto o
          apontamento não existir;
        * a conformidade sai de ``mes/domain/quality_measures.py`` (Wave 5.1) e
          o operador informa apenas a medida;
        * ``CONFORME`` libera o lote; ``RETRABALHO`` não trava mais (patch
          09/11/2026): o operador retrabalha e mede de novo. ``REFUGO`` da
          primeira peça continua exigindo o crachá do responsável designado,
          autorizado **antes** de a peça ser descartada;
        * inspeção progressiva: cada medição vira uma peça numerada; a 1ª peça
          conforme é a peça 1 de N e as próximas são medidas aqui mesmo até N.
          Toda não conformidade abre RNC para a tela Decisão de RNC.
        * ``pecas_registradas`` é quantas medições a tela viu gravadas ao
          enviar. O banco a confere com a linha travada: um segundo envio da
          mesma peça (clique duplo, reenvio da rede, outra aba ou outro tablet)
          é recusado, inclusive a 1ª peça não conforme antes da aprovação.
        """

        if not first_piece_gate_is_structured(setor, operacao):
            return _fail(
                "primeira_peca_checklist_nao_aplicavel",
                "Esta operação não usa o checklist de Setup/Qualidade.",
            )
        trava = getattr(self.db, "trava_primeira_peca", None)
        if not callable(trava):
            trava = lambda *_: nullcontext()  # noqa: E731 - fakes de teste
        with trava(limpa_codigo(op), _operation_id(operacao)):
            return self._registrar_checklist(
                op=op, setor=setor, recurso=recurso, operacao=operacao, medidas=medidas,
                destino=destino, cracha_responsavel=cracha_responsavel, observacao=observacao,
                apontamento_id=apontamento_id, pecas_registradas=pecas_registradas,
            )

    def _registrar_checklist(
        self, *, op, setor, recurso, operacao, medidas, destino, cracha_responsavel,
        observacao, apontamento_id, pecas_registradas,
    ):
        linha = self._linha(op, operacao)
        # Senha conferida antes de qualquer escrita (Codex, rodada 3): uma tela
        # atrasada não pode regravar a decisão da 1ª peça para depois ser
        # recusada só na hora de gravar a medição.
        if pecas_registradas is not None and int(pecas_registradas) != int(
            (linha or {}).get("inspecao_pecas_registradas") or 0
        ):
            return self._peca_ja_registrada(linha)
        if linha and linha.get("bloqueio_ativo"):
            return _fail(
                "primeira_peca_bloqueada",
                "A OP está bloqueada pelo retrabalho da primeira peça. "
                "Chame o responsável para liberar com o crachá dele.",
                self._publico(linha),
            )
        # O formulário é validado antes de qualquer escrita: um envio recusado
        # não pode deixar rastro de estado no posto.
        checklist = self.checklist(setor=setor, operacao=operacao, registro=linha)
        cotas_template = ((checklist or {}).get("template") or {}).get("cotas") or ()
        if not cotas_template:
            return _fail(
                "primeira_peca_checklist_ausente",
                "Cadastre as cotas padrão deste produto antes de liberar o lote.",
                {"checklist": checklist},
            )
        cotas, erro = resolve_checklist_measures(cotas_template, medidas)
        if erro is not None:
            return _fail(erro.code, erro.message, {"checklist": checklist})

        conforme_atual = not any(
            cota["status"] == QUALITY_MEASURE_NON_CONFORMING for cota in cotas
        )
        # Reenvio do mesmo formulário não pode inspecionar duas vezes a peça
        # que já liberou o lote: o portão devolve o mesmo desfecho. Mas isso só
        # vale quando o novo envio também dá conforme — uma correção com cota
        # fora da faixa (refugo/retrabalho) precisa ser processada de verdade,
        # nunca silenciada pelo resultado antigo.
        if linha and linha.get("status") == FIRST_PIECE_CONFORMING and self._faltam_pecas(linha):
            # 2º estágio do setup: a 1ª peça já liberou e as próximas são
            # medidas uma a uma. Sem destino e sem crachá: a não conformidade
            # vira RNC para a Decisão de RNC.
            return self._registrar_peca_progressiva(
                linha, cotas, conforme_atual, checklist, setor, operacao, pecas_registradas
            )
        if linha and linha.get("status") == FIRST_PIECE_CONFORMING and conforme_atual:
            gate = self._avaliar(linha, setor, operacao)
            return FirstPieceResult(
                True,
                "Primeira peça aprovada. Lote liberado para produção.",
                "primeira_peca_ja_aprovada",
                {**gate.como_dicionario(), "registro": self._publico(linha)},
            )

        if linha is None:
            linha = self.garantir(
                op=op,
                setor=setor,
                recurso=recurso,
                operacao=operacao,
                apontamento_id=apontamento_id,
            )
        if linha is None:
            return _fail(
                "primeira_peca_indisponivel",
                "Não foi possível abrir a primeira peça desta operação.",
            )
        if linha.get("setup_obrigatorio") and not linha.get("setup_registrado_em"):
            # Fonte única de "o Setup foi feito": o apontamento do botão Setup,
            # que já grava `setup_registrado_em` pelo fluxo canônico.
            return _fail(
                "primeira_peca_setup_pendente",
                "Aponte o Setup desta operação pelo botão Setup antes de "
                "liberar o lote.",
                self._publico(linha),
            )

        conforme = conforme_atual
        resultado = (
            FIRST_PIECE_CONFORMING
            if conforme
            else (normalize_first_piece_result(destino) or FIRST_PIECE_REWORK)
        )
        if not conforme and resultado == FIRST_PIECE_CONFORMING:
            # Nenhum destino informado pelo operador pode transformar uma cota
            # fora da faixa em peça aprovada.
            resultado = FIRST_PIECE_REWORK
        if resultado == FIRST_PIECE_SCRAP:
            # Descartar a primeira peça é decisão de responsável, não do posto:
            # a autorização é validada e auditada **antes** do descarte, com o
            # mesmo cadastro de crachá usado pelo retrabalho.
            autorizacao = self.autorizar_refugo(
                op=op,
                setor=setor,
                recurso=recurso,
                operacao=operacao,
                cracha=cracha_responsavel,
                registro=linha,
                observacao=observacao,
            )
            if not autorizacao.ok:
                return FirstPieceResult(
                    False,
                    autorizacao.message,
                    autorizacao.code,
                    {**(autorizacao.data or {}), "checklist": checklist, "cotas": cotas},
                )

        producao = self.registrar_producao(
            op=op,
            setor=setor,
            recurso=recurso,
            operacao=operacao,
            apontamento_id=apontamento_id,
        )
        if not producao.ok:
            return producao

        inspecao = self.inspecionar(
            op=op,
            setor=setor,
            recurso=recurso,
            operacao=operacao,
            resultado=resultado,
            observacao=self._observacao_checklist(
                cotas,
                observacao,
                revisao=((checklist or {}).get("template") or {}).get("revisao"),
            ),
        )
        if not inspecao.ok:
            return FirstPieceResult(
                False,
                inspecao.message,
                inspecao.code,
                {**(inspecao.data or {}), "checklist": checklist, "cotas": cotas},
            )
        progressiva = self._gravar_peca_progressiva(
            ((inspecao.data or {}).get("registro") or {}).get("id") or linha["id"],
            cotas,
            conforme,
            pecas_registradas,
        )
        if progressiva and progressiva.get("repetida"):
            return self._peca_ja_registrada(progressiva["primeira_peca"])
        dados = dict(inspecao.data or {})
        if progressiva and progressiva.get("primeira_peca"):
            registro = progressiva["primeira_peca"]
            dados.update(self._avaliar(registro, setor, operacao).como_dicionario())
            dados["registro"] = self._publico(registro)
        mensagem = inspecao.message
        if conforme:
            mensagem = self._mensagem_progressiva(dados) or (
                "Primeira peça aprovada. Lote liberado para produção."
            )
        return FirstPieceResult(
            True,
            mensagem,
            inspecao.code,
            {
                **dados,
                "checklist": checklist,
                "cotas": cotas,
                "conforme": conforme,
                "rnc": (progressiva or {}).get("rnc"),
            },
        )

    OBSERVACAO_SEM_COTAS = "Liberado sem cotas pela administração (teste)."

    def liberar_sem_cotas_teste(self, *, op, setor, recurso, operacao, apontamento_id=None):
        """Atalho de teste só para admin (pedido do usuário, 10/11/2026).

        Faz o mesmo caminho da aprovação normal — 1ª peça conforme e as N peças
        da inspeção progressiva gravadas como conformes, sem medidas — para que
        o lote conte como OP sem NC (o nível desce 1, como no fluxo real). Não
        exige cotas cadastradas. A permissão é conferida na rota.
        """

        if not first_piece_gate_is_structured(setor, operacao):
            return _fail(
                "primeira_peca_checklist_nao_aplicavel",
                "Esta operação não usa o checklist de Setup/Qualidade.",
            )
        trava = getattr(self.db, "trava_primeira_peca", None)
        if not callable(trava):
            trava = lambda *_: nullcontext()  # noqa: E731 - fakes de teste
        with trava(limpa_codigo(op), _operation_id(operacao)):
            return self._liberar_sem_cotas_teste(
                op=op, setor=setor, recurso=recurso, operacao=operacao,
                apontamento_id=apontamento_id,
            )

    def _liberar_sem_cotas_teste(self, *, op, setor, recurso, operacao, apontamento_id):
        linha = self._linha(op, operacao)
        if linha and linha.get("bloqueio_ativo"):
            return _fail(
                "primeira_peca_bloqueada",
                "A OP está bloqueada pelo retrabalho da primeira peça.",
                self._publico(linha),
            )
        if not (linha and linha.get("status") == FIRST_PIECE_CONFORMING):
            if linha is None:
                linha = self.garantir(
                    op=op, setor=setor, recurso=recurso, operacao=operacao,
                    apontamento_id=apontamento_id,
                )
            if linha is None:
                return _fail(
                    "primeira_peca_indisponivel",
                    "Não foi possível abrir a primeira peça desta operação.",
                )
            if linha.get("setup_obrigatorio") and not linha.get("setup_registrado_em"):
                return _fail(
                    "primeira_peca_setup_pendente",
                    "Aponte o Setup desta operação pelo botão Setup antes de liberar o lote.",
                    self._publico(linha),
                )
            producao = self.registrar_producao(
                op=op, setor=setor, recurso=recurso, operacao=operacao,
                apontamento_id=apontamento_id,
            )
            if not producao.ok:
                return producao
            inspecao = self.inspecionar(
                op=op, setor=setor, recurso=recurso, operacao=operacao,
                resultado=FIRST_PIECE_CONFORMING, observacao=self.OBSERVACAO_SEM_COTAS,
            )
            if not inspecao.ok:
                return inspecao
            # Relê a linha: o N acabou de ser fixado pela aprovação.
            linha = self._linha(op, operacao) or linha
        # Grava as peças que faltam como conformes, uma a uma pelo mesmo
        # caminho da medição: é ele que desce o nível ao completar sem NC.
        exigidas = int(linha.get("inspecao_pecas_exigidas") or 0)
        for _ in range(max(exigidas, 1)):
            progressiva = self._gravar_peca_progressiva(linha["id"], (), True)
            if not progressiva or not progressiva.get("primeira_peca"):
                break
            linha = progressiva["primeira_peca"]
            if not self._faltam_pecas(linha):
                break
        linha = self._linha(op, operacao) or linha
        if self._faltam_pecas(linha):
            # Não diz "liberado" se alguma peça não foi gravada (o nível não desceu).
            return _fail(
                "primeira_peca_liberacao_incompleta",
                "Não foi possível completar o lote sem cotas. Tente de novo.",
                self._publico(linha),
            )
        gate = self._avaliar(linha, setor, operacao).como_dicionario()
        return FirstPieceResult(
            True,
            "Setup liberado sem cotas (teste). O lote está liberado.",
            "primeira_peca_liberada_sem_cotas",
            {**gate, "registro": self._publico(linha)},
        )

    # ------------------------------------------------------------------
    # Inspeção progressiva (patch 09/11/2026)
    # ------------------------------------------------------------------
    @staticmethod
    def _faltam_pecas(linha):
        exigidas = linha.get("inspecao_pecas_exigidas")
        return exigidas is not None and int(linha.get("inspecao_pecas_medidas") or 0) < int(exigidas)

    @staticmethod
    def _motivo_nc(cotas):
        fora = [
            f"Cota {cota['sequencia']}: {cota['medida']} {cota['unidade']}"
            + (f" (padrão {cota['padrao']})" if cota.get("padrao") else "")
            for cota in cotas or ()
            if cota["status"] == QUALITY_MEASURE_NON_CONFORMING
        ]
        return ("Fora da tolerância · " + "; ".join(fora))[:500]

    def _gravar_peca_progressiva(self, primeira_peca_id, cotas, conforme, pecas_registradas=None):
        return self.db.registrar_peca_inspecao_progressiva(
            primeira_peca_id,
            conforme=bool(conforme),
            medidas=[
                {chave: cota.get(chave) for chave in ("sequencia", "padrao", "medida", "unidade", "status")}
                for cota in cotas or ()
            ],
            operador=self.operador,
            motivo=None if conforme else self._motivo_nc(cotas),
            instante=self._now(),
            pecas_registradas_esperadas=pecas_registradas,
        )

    def _peca_ja_registrada(self, linha):
        return _fail(
            "primeira_peca_ja_registrada",
            "Esta peça já foi registrada (envio repetido). Atualize o posto.",
            self._publico(linha),
        )

    @staticmethod
    def _mensagem_progressiva(gate):
        exigidas = int(gate.get("pecas_exigidas") or 0)
        medidas = int(gate.get("pecas_medidas") or 0)
        if medidas < exigidas:
            return f"Peça {medidas} de {exigidas} conforme. Meça as cotas da peça {medidas + 1}."
        return None

    def _registrar_peca_progressiva(
        self, linha, cotas, conforme, checklist, setor, operacao, pecas_registradas=None
    ):
        progressiva = self._gravar_peca_progressiva(linha["id"], cotas, conforme, pecas_registradas)
        if progressiva and progressiva.get("repetida"):
            return self._peca_ja_registrada(progressiva["primeira_peca"])
        if not progressiva:
            return _fail(
                "primeira_peca_estado_alterado",
                "A situação da inspeção mudou. Atualize o posto e tente novamente.",
                self._publico(linha),
            )
        registro = progressiva["primeira_peca"]
        gate = self._avaliar(registro, setor, operacao).como_dicionario()
        numero = int(registro.get("inspecao_pecas_medidas") or 0)
        exigidas = int(registro.get("inspecao_pecas_exigidas") or 0)
        if conforme:
            mensagem = self._mensagem_progressiva(gate) or (
                f"Peça {numero} de {exigidas} conforme. Inspeção concluída; o lote está liberado."
            )
            codigo = "inspecao_progressiva_conforme"
        else:
            # NC não avança: a mesma peça é refeita no mesmo número.
            mensagem = (
                f"Peça {numero + 1} de {exigidas} não conforme. A RNC "
                f"{progressiva['rnc']['codigo']} foi aberta para a Qualidade decidir. "
                f"Refaça a peça {numero + 1} de {exigidas} e meça as cotas de novo."
            )
            codigo = "inspecao_progressiva_nao_conforme"
        return FirstPieceResult(
            True,
            mensagem,
            codigo,
            {
                **gate,
                "registro": self._publico(registro),
                "checklist": checklist,
                "cotas": cotas,
                "conforme": bool(conforme),
                "rnc": progressiva.get("rnc"),
            },
        )

    @staticmethod
    def _observacao_checklist(cotas, observacao=None, revisao=None):
        """Resume o checklist no campo de observação que já existe.

        As medidas não ganham tabela nova: elas ficam legíveis no registro da
        primeira peça, ao lado do que o operador escreveu. O texto é também o
        snapshot da genealogia: grava a revisão do template e o padrão de cada
        cota **vigentes na inspeção**, para que editar o template depois não
        mude o critério de um registro já gravado. Formato:

            Template rev 3 · Cota 1: 1200,0 +/- 1,0 → 1200,4 mm (conforme); ...
        """

        def cota_texto(cota):
            status = (
                "não conforme"
                if cota["status"] == QUALITY_MEASURE_NON_CONFORMING
                else "conforme"
            )
            padrao = _texto(cota.get("padrao"), 60)
            medida = f"{cota['medida']} {cota['unidade']} ({status})"
            alvo = f"{padrao} → {medida}" if padrao else medida
            return f"Cota {cota['sequencia']}: {alvo}"

        resumo = "; ".join(cota_texto(cota) for cota in cotas or ())
        if resumo and revisao:
            resumo = f"Template rev {revisao} · {resumo}"
        nota = _texto(observacao, 300)
        # A nota do operador sempre sobrevive; só o resumo das cotas é cortado
        # (com reticências) quando passa do limite do campo.
        espaco = OBSERVACAO_INSPECAO_LIMITE - (len(nota) + 3 if nota else 0)
        if len(resumo) > espaco:
            resumo = resumo[: espaco - 1] + "…"
        return " | ".join(part for part in (resumo, nota) if part)

    def autorizar(self, *, op, setor, recurso, operacao, cracha, observacao=None):
        """Valida o crachá do responsável e libera o bloqueio, com auditoria.

        Toda tentativa é gravada — inclusive a recusada. É ela que prova, na
        homologação, que um crachá não autorizado foi realmente barrado.
        """

        codigo_cracha = _texto(cracha, 60)
        linha = self._linha(op, operacao)
        if linha is None or not linha.get("bloqueio_ativo"):
            return _fail(
                "primeira_peca_sem_bloqueio",
                "Esta operação não possui bloqueio de primeira peça para liberar.",
            )
        estado_antes = self._publico(linha)
        operador, falha = self._responsavel_autorizado(
            codigo_cracha,
            linha,
            estado_antes,
            acao="liberar o retrabalho da primeira peça",
        )
        if falha is not None:
            return falha

        liberada = self.db.liberar_primeira_peca_bloqueada(
            linha["id"],
            cracha=codigo_cracha,
            nome=operador.get("nome"),
            instante=self._now(),
        )
        if liberada is None:
            self._auditar(
                linha,
                codigo_cracha,
                "RECUSADA",
                "O bloqueio mudou de estado antes da liberação.",
                estado_antes,
                nome=operador.get("nome"),
            )
            return _fail(
                "primeira_peca_estado_alterado",
                "A situação da primeira peça mudou. Atualize o posto e tente novamente.",
            )
        self._auditar(
            liberada,
            codigo_cracha,
            "AUTORIZADA",
            observacao,
            estado_antes,
            nome=operador.get("nome"),
            estado_depois=self._publico(liberada),
        )
        self._alertas.primeira_peca_liberada(
            self._contexto(liberada),
            cracha=codigo_cracha,
            autorizado_por=operador.get("nome"),
        )
        gate = self._avaliar(liberada, setor, operacao)
        return FirstPieceResult(
            True,
            f"Liberado por {operador.get('nome') or codigo_cracha}. "
            "Reinspecione a primeira peça para liberar o lote.",
            "primeira_peca_liberada",
            {**gate.como_dicionario(), "registro": self._publico(liberada)},
        )

    def autorizar_refugo(
        self, *, op, setor, recurso, operacao, cracha, registro=None, observacao=None
    ):
        """Autoriza o descarte da primeira peça com o crachá do responsável.

        É o mesmo cadastro, a mesma validação e a mesma auditoria do retrabalho
        (``autorizador_retrabalho``): descartar peça é decisão de responsável,
        não do posto. A autorização acontece **antes** do descarte, então o
        refugo continua sem bloqueio de OP — o que ele exige é o crachá.
        """

        del recurso, setor  # o contexto auditado vem da própria primeira peça
        linha = registro or self._linha(op, operacao)
        if linha is None:
            return _fail(
                "primeira_peca_inexistente",
                "Registre a primeira peça antes de autorizar o refugo dela.",
            )
        estado_antes = self._publico(linha)
        operador, falha = self._responsavel_autorizado(
            _texto(cracha, 60),
            linha,
            estado_antes,
            acao="autorizar o refugo da primeira peça",
            ocorrencia=FIRST_PIECE_SCRAP_OCCURRENCE,
        )
        if falha is not None:
            return falha
        self._auditar(
            linha,
            _texto(cracha, 60),
            "AUTORIZADA",
            observacao,
            estado_antes,
            nome=operador.get("nome"),
            ocorrencia=FIRST_PIECE_SCRAP_OCCURRENCE,
        )
        return FirstPieceResult(
            True,
            f"Refugo autorizado por {operador.get('nome') or _texto(cracha, 60)}.",
            "primeira_peca_refugo_autorizado",
            {"autorizado_por": operador.get("nome"), "cracha": _texto(cracha, 60)},
        )

    # ------------------------------------------------------------------
    # Internos
    # ------------------------------------------------------------------
    def _responsavel_autorizado(
        self, codigo_cracha, linha, estado_antes, *, acao, ocorrencia=None
    ):
        """Valida o crachá do responsável designado e audita toda tentativa.

        Autoridade única sobre "quem pode autorizar exceção de qualidade no
        posto": o cadastro de crachás com ``autorizador_retrabalho``. Não
        existe login, perfil novo nem segunda lista.
        """

        def recusar(code, mensagem, motivo, nome=None):
            self._auditar(
                linha,
                codigo_cracha,
                "RECUSADA",
                motivo,
                estado_antes,
                nome=nome,
                ocorrencia=ocorrencia,
            )
            return None, _fail(code, mensagem)

        if not codigo_cracha:
            return recusar(
                "primeira_peca_cracha_obrigatorio",
                f"Informe o crachá do responsável para {acao}.",
                "Crachá não informado.",
            )
        finder = getattr(self.db, "buscar_operador_apontamento_detalhado", None)
        operador = finder(codigo_cracha) if callable(finder) else None
        if operador is None:
            return recusar(
                "primeira_peca_cracha_invalido",
                f"Crachá {codigo_cracha} não cadastrado.",
                "Crachá não cadastrado.",
            )
        if not operador.get("ativo"):
            return recusar(
                "primeira_peca_cracha_inativo",
                f"Crachá {codigo_cracha} está inativo.",
                "Crachá inativo.",
            )
        if not operador.get("autorizador_retrabalho"):
            return recusar(
                "primeira_peca_cracha_nao_autorizado",
                f"O crachá {codigo_cracha} não está autorizado a {acao}.",
                "Crachá não é responsável autorizado para este chamado.",
                nome=operador.get("nome"),
            )
        return operador, None

    def _linha(self, op, operacao):
        finder = getattr(self.db, "buscar_primeira_peca", None)
        if not callable(finder):
            return None
        try:
            return finder(limpa_codigo(op), _operation_id(operacao))
        except Exception:  # pragma: no cover
            logging.exception("Falha ao ler a primeira peça da OP %s.", op)
            return None

    def _avaliar(self, linha, setor, operacao=None) -> FirstPieceGate:
        dados = dict(linha or {})
        estruturado = first_piece_gate_is_structured(setor, operacao)
        if not dados:
            return evaluate_first_piece_gate(
                aplicavel=True,
                status=FIRST_PIECE_PENDING,
                peca_produzida=False,
                setup_obrigatorio=self.setup_obrigatorio(setor),
                setup_registrado=False,
                bloqueio_ativo=False,
                gate_estruturado=estruturado,
            )
        return evaluate_first_piece_gate(
            aplicavel=True,
            status=dados.get("status") or FIRST_PIECE_PENDING,
            peca_produzida=bool(dados.get("peca_produzida_em")),
            setup_obrigatorio=bool(dados.get("setup_obrigatorio")),
            setup_registrado=bool(dados.get("setup_registrado_em")),
            bloqueio_ativo=bool(dados.get("bloqueio_ativo")),
            gate_estruturado=estruturado,
            pecas_exigidas=dados.get("inspecao_pecas_exigidas"),
            pecas_medidas=int(dados.get("inspecao_pecas_medidas") or 0),
        )

    @staticmethod
    def _produto(operacao, registro=None):
        dados = dict(operacao or {})
        return str(
            dados.get("produto_codigo")
            or dict(registro or {}).get("produto_codigo")
            or ""
        ).strip()

    @staticmethod
    def _publico(linha):
        if not linha:
            return None
        dados = dict(linha)
        return {
            "id": dados.get("id"),
            "op": dados.get("codigo_op"),
            "operacao": dados.get("numero_operacao"),
            "catalogo_operacao_id": dados.get("catalogo_operacao_id"),
            "produto": dados.get("produto_codigo"),
            "produto_descricao": dados.get("produto_descricao"),
            "setor": dados.get("tipo_setor"),
            "recurso": dados.get("recurso_apontado") or dados.get("codigo_recurso"),
            "quantidade_planejada": dados.get("quantidade_planejada"),
            "status": dados.get("status"),
            "resultado": dados.get("resultado"),
            "observacao": dados.get("observacao"),
            "peca_produzida_em": dados.get("peca_produzida_em"),
            "peca_produzida_por": dados.get("peca_produzida_por"),
            "setup_obrigatorio": bool(dados.get("setup_obrigatorio")),
            "setup_registrado_em": dados.get("setup_registrado_em"),
            "inspecionada_em": dados.get("inspecionada_em"),
            "inspecionada_por": dados.get("inspecionada_por"),
            "bloqueio_ativo": bool(dados.get("bloqueio_ativo")),
            "bloqueio_ocorrencia": dados.get("bloqueio_ocorrencia"),
            "liberada_em": dados.get("liberada_em"),
            "liberada_por_cracha": dados.get("liberada_por_cracha"),
            "liberada_por_nome": dados.get("liberada_por_nome"),
            "tentativas": dados.get("tentativas"),
            "inspecao_pecas_exigidas": dados.get("inspecao_pecas_exigidas"),
            "inspecao_pecas_medidas": int(dados.get("inspecao_pecas_medidas") or 0),
            "inspecao_com_nc": bool(dados.get("inspecao_com_nc")),
        }

    @staticmethod
    def _contexto(linha):
        dados = dict(linha or {})
        return {
            "codigo_op": dados.get("codigo_op"),
            "catalogo_operacao_id": dados.get("catalogo_operacao_id"),
            "numero_operacao": dados.get("numero_operacao"),
            "tipo_setor": dados.get("tipo_setor"),
            "codigo_recurso": dados.get("codigo_recurso"),
            "recurso_apontado": dados.get("recurso_apontado"),
            "produto_codigo": dados.get("produto_codigo"),
        }

    def _auditar(
        self,
        linha,
        cracha,
        decisao,
        motivo,
        estado_antes,
        *,
        nome=None,
        estado_depois=None,
        ocorrencia=None,
    ):
        registrar = getattr(self.db, "registrar_autorizacao_primeira_peca", None)
        if not callable(registrar):
            return
        dados = dict(linha or {})
        try:
            registrar(
                primeira_peca_id=dados.get("id"),
                codigo_op=dados.get("codigo_op"),
                catalogo_operacao_id=dados.get("catalogo_operacao_id"),
                numero_operacao=dados.get("numero_operacao"),
                tipo_setor=dados.get("tipo_setor"),
                codigo_recurso=dados.get("codigo_recurso"),
                recurso_apontado=dados.get("recurso_apontado"),
                operador=self.operador,
                ocorrencia=ocorrencia
                or dados.get("bloqueio_ocorrencia")
                or FIRST_PIECE_BLOCK_OCCURRENCE,
                cracha=cracha,
                autorizado_por_nome=nome,
                decisao=decisao,
                motivo_recusa=None if decisao == "AUTORIZADA" else motivo,
                estado_antes=estado_antes,
                estado_depois=estado_depois,
                data_hora=self._now(),
            )
        except Exception:  # pragma: no cover - auditoria não bloqueia o fluxo
            logging.exception("Falha ao auditar a autorização da primeira peça.")


__all__ = [
    "FIRST_PIECE_CONFORMING",
    "FIRST_PIECE_PRODUCED",
    "FirstPieceResult",
    "FirstPieceService",
]
