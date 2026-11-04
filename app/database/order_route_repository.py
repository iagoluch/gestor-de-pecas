"""Consulta de OP e etapas adicionadas no Gestor ao roteiro (migration 72).

A etapa adicionada mora em ``catalogo_operacoes_op`` (``etapa_gestor = TRUE``,
``fonte = 'gestor_etapa_adicional'``) para que fila, apontamento e Andon a
tratem como qualquer operação. Ela nunca tem ``totvs_activity_id``: a
re-sincronização do Protheus não a toca (ver ``realinhar_etapas_gestor_cursor``)
e o outbound TOTVS a ignora.
"""

from __future__ import annotations

from datetime import datetime

FONTE_ETAPA_GESTOR = "gestor_etapa_adicional"
STATUS_EM_ABERTO = ("Aguardando", "Em processo", "Parada", "Setup", "Retrabalho")


class OrderRouteRepositoryMixin:
    def buscar_ops_para_consulta(self, termo, limite=20):
        pattern = f"%{str(termo or '').strip()}%"
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT codigo_op, produto_codigo, produto_descricao, quantidade, status_pcp
                FROM catalogo_pcp_ops
                WHERE codigo_op ILIKE %s OR produto_codigo ILIKE %s OR produto_descricao ILIKE %s
                ORDER BY codigo_op DESC
                LIMIT %s
                """,
                (pattern, pattern, pattern, int(limite)),
            )
            return [dict(row) for row in cursor.fetchall()]

    def obter_op_para_consulta(self, codigo_op):
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT * FROM catalogo_pcp_ops WHERE codigo_op = %s", (codigo_op,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def resumir_passagem_op(self, codigo_op):
        """Quanto a OP já andou no Gestor: linhas de fila/apontamento e quantas começaram."""

        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT COUNT(*) AS apontamentos,
                       COUNT(*) FILTER (WHERE data_inicio IS NOT NULL) AS iniciados,
                       MIN(data_entrada) AS primeira_entrada,
                       MAX(COALESCE(data_fim, data_inicio, data_entrada)) AS ultima_atividade
                FROM apontamentos_operacionais
                WHERE op = %s
                """,
                (codigo_op,),
            )
            return dict(cursor.fetchone())

    def listar_roteiro_para_consulta(self, codigo_op):
        """Roteiro vigente inteiro (marcos/inspeção do último snapshot incluídos),
        mais as etapas do Gestor (ativas ou desativadas), com a execução de cada uma."""

        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    o.id, o.ordem, o.numero_operacao, o.descricao_operacao, o.tipo_setor,
                    o.codigo_recurso, r.nome AS recurso_nome, o.tempo_medio_segundos,
                    o.ativo, o.marco_terminal, o.inspecao_qualidade, o.etapa_gestor,
                    o.apos_operacao_id, o.adicionada_por_nome, o.adicionada_em,
                    o.motivo_adicao, o.desativada_por_nome, o.desativada_em,
                    o.motivo_desativacao,
                    ap.status AS execucao_status,
                    COALESCE(ap.quantidade_boa, 0) AS quantidade_boa
                FROM catalogo_operacoes_op o
                LEFT JOIN catalogo_recursos_pcfactory r ON r.codigo = o.codigo_recurso
                LEFT JOIN LATERAL (
                    SELECT a.status, a.quantidade_boa
                    FROM apontamentos_operacionais a
                    WHERE a.catalogo_operacao_id = o.id
                    ORDER BY a.id DESC
                    LIMIT 1
                ) ap ON TRUE
                WHERE o.codigo_op = %s
                  AND (
                        o.ativo IS TRUE
                        OR o.etapa_gestor IS TRUE
                        OR (
                            o.fonte = 'totvs_production_order_v1'
                            AND o.sincronizado_em = (
                                SELECT MAX(atual.sincronizado_em)
                                FROM catalogo_operacoes_op atual
                                WHERE atual.codigo_op = o.codigo_op
                                  AND atual.fonte = 'totvs_production_order_v1'
                            )
                        )
                  )
                ORDER BY o.ordem, o.id
                """,
                (codigo_op,),
            )
            return [dict(row) for row in cursor.fetchall()]

    def listar_recursos_catalogo_para_etapa(self):
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT codigo, nome, tipo_setor FROM catalogo_recursos_pcfactory"
                " WHERE habilitado IS TRUE ORDER BY tipo_setor, nome"
            )
            return [dict(row) for row in cursor.fetchall()]

    def inserir_etapa_gestor(
        self, *, codigo_op, apos_operacao_id, descricao, tipo_setor, codigo_recurso,
        motivo, usuario_id, usuario_nome, agora=None,
    ):
        """Insere a etapa depois de ``apos_operacao_id`` (``None`` = início).

        Devolve ``(linha, anterior)`` ou levanta ``LookupError`` (OP/âncora
        inexistente). ``ordem`` = ordem da âncora: o desempate por ``id`` (sempre
        maior que o da âncora) a posiciona logo depois dela.
        """

        agora = agora or datetime.now()
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT codigo_op, produto_codigo, produto_descricao, filial"
                " FROM catalogo_pcp_ops WHERE codigo_op = %s FOR UPDATE",
                (codigo_op,),
            )
            op = cursor.fetchone()
            if op is None:
                raise LookupError("op")
            ordem, anterior_numero = 0, None
            if apos_operacao_id is not None:
                cursor.execute(
                    "SELECT ordem, numero_operacao FROM catalogo_operacoes_op"
                    " WHERE id = %s AND codigo_op = %s AND ativo IS TRUE",
                    (int(apos_operacao_id), codigo_op),
                )
                ancora = cursor.fetchone()
                if ancora is None:
                    raise LookupError("ancora")
                ordem, anterior_numero = int(ancora["ordem"]), ancora["numero_operacao"]
            cursor.execute(
                "SELECT COUNT(*) AS total FROM catalogo_operacoes_op"
                " WHERE codigo_op = %s AND etapa_gestor IS TRUE",
                (codigo_op,),
            )
            numero = f"G{int(cursor.fetchone()['total']) + 1:02d}"
            cursor.execute(
                """
                INSERT INTO catalogo_operacoes_op (
                    codigo_op, produto_codigo, produto_descricao, numero_operacao,
                    codigo_recurso, descricao_operacao, tipo_setor, filial, tipo,
                    roteiro, tempo_medio_segundos, ordem, fonte, ativo,
                    sincronizado_em, etapa_gestor, apos_operacao_id,
                    adicionada_por_id, adicionada_por_nome, adicionada_em, motivo_adicao
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, NULL, NULL, NULL, %s, %s, TRUE,
                    %s, TRUE, %s, %s, %s, %s, %s
                )
                RETURNING id, numero_operacao, ordem
                """,
                (
                    codigo_op, op["produto_codigo"], op["produto_descricao"] or "",
                    numero, codigo_recurso, descricao, tipo_setor, op["filial"],
                    ordem, FONTE_ETAPA_GESTOR, agora,
                    int(apos_operacao_id) if apos_operacao_id is not None else None,
                    usuario_id, usuario_nome, agora, motivo,
                ),
            )
            return dict(cursor.fetchone()), anterior_numero

    def desativar_etapa_gestor(self, *, codigo_op, etapa_id, motivo, usuario_nome, agora=None):
        """Desativa (nunca apaga) uma etapa do Gestor.

        Devolve a linha desativada; ``None`` se não for etapa do Gestor ativa
        dessa OP; levanta ``ValueError`` se já houve apontamento nela.
        """

        agora = agora or datetime.now()
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT id, numero_operacao, descricao_operacao, tipo_setor, codigo_recurso"
                " FROM catalogo_operacoes_op"
                " WHERE id = %s AND codigo_op = %s AND etapa_gestor IS TRUE AND ativo IS TRUE"
                " FOR UPDATE",
                (int(etapa_id), codigo_op),
            )
            etapa = cursor.fetchone()
            if etapa is None:
                return None
            cursor.execute(
                "SELECT 1 FROM apontamentos_operacionais WHERE catalogo_operacao_id = %s LIMIT 1",
                (int(etapa_id),),
            )
            if cursor.fetchone():
                raise ValueError("apontada")
            cursor.execute(
                "UPDATE catalogo_operacoes_op SET ativo = FALSE, desativada_por_nome = %s,"
                " desativada_em = %s, motivo_desativacao = %s WHERE id = %s",
                (usuario_nome, agora, motivo, int(etapa_id)),
            )
            return dict(etapa)

    @staticmethod
    def realinhar_etapas_gestor_cursor(cursor, codigo_op):
        """Reposiciona as etapas do Gestor depois da re-sincronização da OP.

        O Protheus renumera ``ordem``; a etapa do Gestor segue a operação
        âncora (``apos_operacao_id``, id estável entre sincronizações). Percorre
        por ``id`` para que âncora que é outra etapa do Gestor já esteja ajustada.
        """

        cursor.execute(
            "SELECT id, apos_operacao_id FROM catalogo_operacoes_op"
            " WHERE codigo_op = %s AND etapa_gestor IS TRUE AND apos_operacao_id IS NOT NULL"
            " ORDER BY id",
            (codigo_op,),
        )
        for etapa in cursor.fetchall():
            cursor.execute(
                "UPDATE catalogo_operacoes_op SET ordem = ancora.ordem"
                " FROM catalogo_operacoes_op ancora"
                " WHERE ancora.id = %s AND catalogo_operacoes_op.id = %s",
                (etapa["apos_operacao_id"], etapa["id"]),
            )
