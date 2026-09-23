"""Persistência da primeira peça, da autorização por crachá e dos alertas internos.

Este repositório não decide regra industrial. Ele grava e lê o que
``mes/services/first_piece.py`` e ``mes/services/internal_alerts.py`` já
validaram, e concentra as garantias que só o banco pode dar:

* uma única linha de primeira peça por operação do roteiro
  (``uq_primeira_peca_operacao``), inclusive sob concorrência de dois postos;
* bloqueio ativo apenas quando o resultado é ``RETRABALHO``
  (``ck_primeira_peca_bloqueio``);
* toda tentativa de autorização gravada, aceita **ou** recusada.

Nada aqui fala com TOTVS, SigmaNEST ou Telegram. Alerta interno é obrigação de
avisar alguém, não entrega.
"""

from __future__ import annotations

from datetime import datetime
import json

from app.core.normalization import limpa_codigo
from mes.domain.first_piece import (
    FIRST_PIECE_PENDING,
    FIRST_PIECE_PRODUCED,
    FIRST_PIECE_SCRAP,
)
from mes.domain.internal_alerts import (
    CHANNEL_TELEGRAM,
    NOTIFICATION_PENDING,
    SEVERITY_INFO,
)


def _as_dict(row):
    return dict(row) if row else None


def _texto(valor, limite=200):
    return str(valor or "").strip()[:limite] or None


def _detalhes(valor):
    if valor is None:
        return None
    if isinstance(valor, str):
        return valor
    return json.dumps(valor, ensure_ascii=False, sort_keys=True, default=str)


class FirstPieceRepositoryMixin:
    # ------------------------------------------------------------------
    # Primeira peça
    # ------------------------------------------------------------------
    def garantir_primeira_peca(self, **valores):
        """Cria (ou devolve) a linha da primeira peça da operação.

        A criação é idempotente por ``(codigo_op, catalogo_operacao_id)``: dois
        postos que iniciem a mesma operação ao mesmo tempo continuam com uma
        única primeira peça, e nenhum deles recebe erro.
        """

        codigo = limpa_codigo(valores.get("codigo_op"))
        operacao_id = valores.get("catalogo_operacao_id")
        instante = valores.get("criada_em") or datetime.now().replace(microsecond=0)
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO qualidade_primeira_peca (
                    codigo_op, catalogo_operacao_id, numero_operacao,
                    apontamento_id, produto_codigo, produto_descricao,
                    tipo_setor, codigo_recurso, recurso_apontado,
                    quantidade_planejada, setup_obrigatorio, status,
                    criada_em, atualizada_em
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
                ON CONFLICT (UPPER(codigo_op), COALESCE(catalogo_operacao_id, -1))
                DO UPDATE SET apontamento_id = COALESCE(
                    qualidade_primeira_peca.apontamento_id, EXCLUDED.apontamento_id
                )
                RETURNING *
                """,
                (
                    codigo,
                    operacao_id,
                    str(valores.get("numero_operacao") or "").strip(),
                    valores.get("apontamento_id"),
                    _texto(valores.get("produto_codigo"), 60),
                    _texto(valores.get("produto_descricao"), 300),
                    str(valores.get("tipo_setor") or "").strip(),
                    _texto(valores.get("codigo_recurso"), 60),
                    _texto(valores.get("recurso_apontado"), 120),
                    max(1, int(valores.get("quantidade_planejada") or 1)),
                    bool(valores.get("setup_obrigatorio")),
                    FIRST_PIECE_PENDING,
                    instante,
                    instante,
                ),
            )
            criada = _as_dict(cursor.fetchone())
            if criada is not None:
                return criada
        return self.buscar_primeira_peca(codigo, operacao_id)

    def buscar_primeira_peca(self, codigo_op, catalogo_operacao_id=None):
        """Primeira peça da operação; sem ``catalogo_operacao_id`` traz a mais recente."""

        query = """
            SELECT * FROM qualidade_primeira_peca
            WHERE UPPER(codigo_op) = UPPER(%s)
        """
        params = [limpa_codigo(codigo_op)]
        if catalogo_operacao_id is not None:
            query += " AND catalogo_operacao_id = %s"
            params.append(int(catalogo_operacao_id))
        query += " ORDER BY atualizada_em DESC, id DESC LIMIT 1"
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(query, params)
            return _as_dict(cursor.fetchone())

    def listar_primeiras_pecas_da_op(self, codigo_op):
        """Todas as primeiras peças da OP, em uma única leitura.

        O roteiro do posto projeta o portão em cada etapa; consultar linha a
        linha transformaria a abertura de uma OP em N consultas.
        """

        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT * FROM qualidade_primeira_peca
                WHERE UPPER(codigo_op) = UPPER(%s)
                ORDER BY id
                """,
                (limpa_codigo(codigo_op),),
            )
            return [dict(row) for row in cursor.fetchall()]

    def buscar_primeira_peca_por_id(self, primeira_peca_id):
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT * FROM qualidade_primeira_peca WHERE id = %s",
                (int(primeira_peca_id),),
            )
            return _as_dict(cursor.fetchone())

    def registrar_primeira_peca_produzida(
        self, primeira_peca_id, *, operador, apontamento_id=None, instante=None
    ):
        """Marca que a primeira peça saiu da máquina. Não aprova nada."""

        momento = instante or datetime.now().replace(microsecond=0)
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE qualidade_primeira_peca
                   SET status = %s,
                       peca_produzida_em = COALESCE(peca_produzida_em, %s),
                       peca_produzida_por = COALESCE(peca_produzida_por, %s),
                       apontamento_id = COALESCE(%s, apontamento_id),
                       tentativas = tentativas + 1,
                       atualizada_em = %s
                 WHERE id = %s
                   AND status IN (%s, %s, %s)
                RETURNING *
                """,
                (
                    FIRST_PIECE_PRODUCED,
                    momento,
                    str(operador or "Operador").strip(),
                    apontamento_id,
                    momento,
                    int(primeira_peca_id),
                    FIRST_PIECE_PENDING,
                    FIRST_PIECE_PRODUCED,
                    FIRST_PIECE_SCRAP,
                ),
            )
            return _as_dict(cursor.fetchone())

    def registrar_setup_primeira_peca(
        self, codigo_op, catalogo_operacao_id=None, *, instante=None
    ):
        """Anota o Setup já apontado pelo fluxo canônico do operador.

        O operador não executa um passo novo: quem chama é o próprio
        ``OperatorFlowService`` depois de o Setup ter sido aceito.
        """

        momento = instante or datetime.now().replace(microsecond=0)
        query = """
            UPDATE qualidade_primeira_peca
               SET setup_registrado_em = COALESCE(setup_registrado_em, %s),
                   atualizada_em = %s
             WHERE UPPER(codigo_op) = UPPER(%s)
        """
        params = [momento, momento, limpa_codigo(codigo_op)]
        if catalogo_operacao_id is not None:
            query += " AND catalogo_operacao_id = %s"
            params.append(int(catalogo_operacao_id))
        query += " RETURNING *"
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(query, params)
            return _as_dict(cursor.fetchone())

    def registrar_inspecao_primeira_peca(
        self,
        primeira_peca_id,
        *,
        resultado,
        operador,
        observacao=None,
        instante=None,
        bloquear=False,
        ocorrencia=None,
    ):
        """Grava a decisão do operador sobre a primeira peça.

        ``bloquear`` só é verdadeiro para ``RETRABALHO``; a constraint
        ``ck_primeira_peca_bloqueio`` recusa qualquer outra combinação.

        Um retrabalho também limpa ``setup_registrado_em``: a máquina que
        produziu a peça rejeitada precisa ser reconferida, então o portão
        volta a exigir Setup antes da próxima finalização (mesma exigência da
        primeira vez). Refugo não mexe no Setup — o defeito é da peça, não do
        ajuste da máquina.
        """

        momento = instante or datetime.now().replace(microsecond=0)
        decisao = str(resultado).strip().upper()
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE qualidade_primeira_peca
                   SET status = %s, resultado = %s, inspecionada_em = %s,
                       inspecionada_por = %s, observacao = %s,
                       bloqueio_ativo = %s, bloqueio_ocorrencia = %s,
                       bloqueio_em = CASE WHEN %s THEN %s ELSE NULL END,
                       setup_registrado_em = CASE WHEN %s THEN NULL ELSE setup_registrado_em END,
                       atualizada_em = %s
                 WHERE id = %s AND bloqueio_ativo IS FALSE
                RETURNING *
                """,
                (
                    decisao, decisao, momento, str(operador or "Operador").strip(),
                    _texto(observacao, 500), bool(bloquear),
                    _texto(ocorrencia, 60) if bloquear else None, bool(bloquear),
                    momento, bool(bloquear), momento, int(primeira_peca_id),
                ),
            )
            primeira_peca = _as_dict(cursor.fetchone())
            if primeira_peca is None or decisao != FIRST_PIECE_SCRAP:
                return primeira_peca

            apontamento_id = primeira_peca.get("apontamento_id")
            if not apontamento_id:
                raise ValueError("O refugo da primeira peça exige um apontamento operacional ativo.")
            cursor.execute("SELECT * FROM apontamentos_operacionais WHERE id = %s FOR UPDATE", (apontamento_id,))
            apontamento = _as_dict(cursor.fetchone())
            if apontamento is None:
                raise ValueError("Apontamento operacional da primeira peça não encontrado.")
            atendida = int(apontamento.get("quantidade_boa") or 0) + int(apontamento.get("quantidade_refugo") or 0)
            if atendida >= int(apontamento.get("quantidade") or 0):
                raise ValueError("O refugo excede a quantidade prevista da OP.")
            cursor.execute(
                "UPDATE apontamentos_operacionais SET quantidade_refugo = quantidade_refugo + 1 WHERE id = %s RETURNING *",
                (apontamento_id,),
            )
            apontamento = _as_dict(cursor.fetchone())
            cursor.execute(
                """
                INSERT INTO eventos_apontamento_operador (
                    apontamento_id, estado, motivo, comentario, quantidade_boa,
                    quantidade_refugo, operador, data_hora
                ) VALUES (%s, 'primeira_peca_refugo', %s, %s, 0, 1, %s, %s)
                RETURNING id
                """,
                (apontamento_id, "Refugo da primeira peça", _texto(observacao, 500), str(operador or "Operador").strip(), momento),
            )
            evento_id = cursor.fetchone()["id"]
            self.registrar_evento_quantidade(
                "refugo", 1, apontamento["op"],
                numero_operacao=apontamento.get("numero_operacao"), produto_codigo=apontamento.get("produto_codigo"),
                recurso=apontamento.get("maquina"), tipo_setor=apontamento.get("tipo_setor"),
                operador=str(operador or "Operador").strip(), motivo="Refugo da primeira peça",
                comentario=_texto(observacao, 500), data_hora=momento, origem="primeira_peca",
                referencia_origem=f"evento_apontamento:{evento_id}", connection=connection,
            )
            self._enfileirar_outbound_totvs_tx(
                cursor, evento_id=evento_id, codigo_op=apontamento.get("op"), execucao_concluida=False,
            )
            return primeira_peca

    def liberar_primeira_peca_bloqueada(
        self, primeira_peca_id, *, cracha, nome, instante=None
    ):
        """Remove o bloqueio depois da autorização do responsável.

        A peça retrabalhada volta a ``PRODUZIDA``: ela existe fisicamente, mas
        ainda não foi aprovada. O lote só é liberado por uma nova inspeção
        ``CONFORME`` — a autorização libera o fluxo, não a qualidade.
        """

        momento = instante or datetime.now().replace(microsecond=0)
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE qualidade_primeira_peca
                   SET bloqueio_ativo = FALSE,
                       status = %s,
                       resultado = NULL,
                       liberada_em = %s,
                       liberada_por_cracha = %s,
                       liberada_por_nome = %s,
                       atualizada_em = %s
                 WHERE id = %s
                   AND bloqueio_ativo IS TRUE
                RETURNING *
                """,
                (
                    FIRST_PIECE_PRODUCED,
                    momento,
                    str(cracha or "").strip(),
                    _texto(nome, 120),
                    momento,
                    int(primeira_peca_id),
                ),
            )
            return _as_dict(cursor.fetchone())

    def listar_primeiras_pecas(
        self, *, tipo_setor=None, status=None, somente_bloqueadas=False, limite=200
    ):
        query = "SELECT * FROM qualidade_primeira_peca WHERE TRUE"
        params: list = []
        if tipo_setor:
            query += " AND UPPER(tipo_setor) = UPPER(%s)"
            params.append(str(tipo_setor).strip())
        if status:
            query += " AND status = %s"
            params.append(str(status).strip().upper())
        if somente_bloqueadas:
            query += " AND bloqueio_ativo IS TRUE"
        query += " ORDER BY atualizada_em DESC, id DESC LIMIT %s"
        params.append(int(limite))
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]

    def resumo_primeira_peca(self):
        """Contagem por estado, usada pelas telas gerenciais e pelo relatório."""

        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT status,
                       COUNT(*) AS total,
                       COUNT(*) FILTER (WHERE bloqueio_ativo IS TRUE) AS bloqueadas
                  FROM qualidade_primeira_peca
                 GROUP BY status
                """
            )
            return [dict(row) for row in cursor.fetchall()]

    # ------------------------------------------------------------------
    # Autorização por crachá
    # ------------------------------------------------------------------
    def registrar_autorizacao_primeira_peca(self, **valores):
        """Auditoria da tentativa: quem, quando, qual crachá e qual decisão."""

        momento = valores.get("data_hora") or datetime.now().replace(microsecond=0)
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO qualidade_primeira_peca_autorizacoes (
                    primeira_peca_id, codigo_op, catalogo_operacao_id,
                    numero_operacao, tipo_setor, codigo_recurso, recurso_apontado,
                    operador, ocorrencia, cracha, autorizado_por_nome,
                    decisao, motivo_recusa, estado_antes, estado_depois, data_hora
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
                RETURNING *
                """,
                (
                    valores.get("primeira_peca_id"),
                    limpa_codigo(valores.get("codigo_op")),
                    valores.get("catalogo_operacao_id"),
                    _texto(valores.get("numero_operacao"), 20),
                    _texto(valores.get("tipo_setor"), 60),
                    _texto(valores.get("codigo_recurso"), 60),
                    _texto(valores.get("recurso_apontado"), 120),
                    _texto(valores.get("operador"), 120),
                    str(valores.get("ocorrencia") or "").strip(),
                    str(valores.get("cracha") or "").strip(),
                    _texto(valores.get("autorizado_por_nome"), 120),
                    str(valores.get("decisao") or "RECUSADA").strip().upper(),
                    _texto(valores.get("motivo_recusa"), 300),
                    _detalhes(valores.get("estado_antes")),
                    _detalhes(valores.get("estado_depois")),
                    momento,
                ),
            )
            return dict(cursor.fetchone())

    def listar_autorizacoes_primeira_peca(self, *, codigo_op=None, limite=200):
        query = "SELECT * FROM qualidade_primeira_peca_autorizacoes WHERE TRUE"
        params: list = []
        if codigo_op:
            query += " AND UPPER(codigo_op) = UPPER(%s)"
            params.append(limpa_codigo(codigo_op))
        query += " ORDER BY data_hora DESC, id DESC LIMIT %s"
        params.append(int(limite))
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]

    def buscar_operador_apontamento_detalhado(self, cracha):
        """Crachá com ``ativo`` e ``autorizador_retrabalho``, sem filtrar nada.

        A tela precisa distinguir "não existe", "existe mas está inativo" e
        "existe, ativo, porém não é responsável designado". Um SELECT que já
        filtra ``ativo`` transforma os três casos na mesma resposta.
        """

        codigo = str(cracha or "").strip()
        if not codigo:
            return None
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT * FROM operadores_apontamento WHERE cracha = %s",
                (codigo,),
            )
            return _as_dict(cursor.fetchone())

    def listar_autorizadores_retrabalho(self):
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT * FROM operadores_apontamento
                WHERE autorizador_retrabalho IS TRUE AND ativo IS TRUE
                ORDER BY nome, cracha
                """
            )
            return [dict(row) for row in cursor.fetchall()]

    def definir_autorizador_retrabalho(self, cracha, autorizado):
        """Designa (ou remove) o crachá como responsável pelo chamado."""

        codigo = str(cracha or "").strip()
        if not codigo:
            raise ValueError("Informe o crachá do responsável.")
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE operadores_apontamento
                   SET autorizador_retrabalho = %s
                 WHERE cracha = %s
                RETURNING *
                """,
                (bool(autorizado), codigo),
            )
            return _as_dict(cursor.fetchone())

    # ------------------------------------------------------------------
    # Alertas internos
    # ------------------------------------------------------------------
    def registrar_alerta_interno(self, **valores):
        """Grava a obrigação de avisar alguém. Nenhuma mensagem é enviada."""

        momento = valores.get("criado_em") or datetime.now().replace(microsecond=0)
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO alertas_internos (
                    tipo, severidade, destinatario, canal_previsto,
                    status_notificacao, codigo_op, catalogo_operacao_id,
                    numero_operacao, tipo_setor, codigo_recurso, produto_codigo,
                    titulo, mensagem, quantidade, detalhes, origem, criado_por,
                    criado_em
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s
                )
                RETURNING *
                """,
                (
                    str(valores.get("tipo") or "").strip().upper(),
                    str(valores.get("severidade") or SEVERITY_INFO).strip().upper(),
                    str(valores.get("destinatario") or "").strip().upper(),
                    str(valores.get("canal_previsto") or CHANNEL_TELEGRAM).strip(),
                    str(
                        valores.get("status_notificacao") or NOTIFICATION_PENDING
                    ).strip().upper(),
                    limpa_codigo(valores.get("codigo_op")) or None,
                    valores.get("catalogo_operacao_id"),
                    _texto(valores.get("numero_operacao"), 20),
                    _texto(valores.get("tipo_setor"), 60),
                    _texto(valores.get("codigo_recurso"), 60),
                    _texto(valores.get("produto_codigo"), 60),
                    str(valores.get("titulo") or "").strip()[:200],
                    str(valores.get("mensagem") or "").strip()[:1000],
                    valores.get("quantidade"),
                    _detalhes(valores.get("detalhes")),
                    str(valores.get("origem") or "Gestor").strip(),
                    _texto(valores.get("criado_por"), 120),
                    momento,
                ),
            )
            return dict(cursor.fetchone())

    def listar_alertas_internos(
        self,
        *,
        destinatario=None,
        tipo=None,
        codigo_op=None,
        somente_pendentes=False,
        limite=200,
    ):
        query = "SELECT * FROM alertas_internos WHERE TRUE"
        params: list = []
        if destinatario:
            query += " AND destinatario = %s"
            params.append(str(destinatario).strip().upper())
        if tipo:
            query += " AND tipo = %s"
            params.append(str(tipo).strip().upper())
        if codigo_op:
            query += " AND UPPER(codigo_op) = UPPER(%s)"
            params.append(limpa_codigo(codigo_op))
        if somente_pendentes:
            query += " AND status_notificacao = 'PENDENTE'"
        query += " ORDER BY criado_em DESC, id DESC LIMIT %s"
        params.append(int(limite))
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]

    def resumo_alertas_internos(self):
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT tipo, destinatario, severidade, status_notificacao,
                       COUNT(*) AS total,
                       COALESCE(SUM(quantidade), 0) AS quantidade_total
                  FROM alertas_internos
                 GROUP BY tipo, destinatario, severidade, status_notificacao
                 ORDER BY tipo, destinatario
                """
            )
            return [dict(row) for row in cursor.fetchall()]


__all__ = ["FirstPieceRepositoryMixin"]
