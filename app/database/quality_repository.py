"""Persistência da inspeção dimensional da Qualidade.

Este repositório não decide regra industrial. Ele grava e lê o que o
``QualityInspectionService`` já validou, e concentra as garantias que só o
banco pode dar: unicidade da unidade inspecionada, unicidade da sessão aberta
por OP e atomicidade entre peça, cotas e RNC.

Nada aqui fala com TOTVS. O movimento empresarial da operação de inspeção
continua sendo produzido pelo fluxo canônico do operador
(``apontamentos_operacionais`` → evento → outbox).
"""

from __future__ import annotations

from datetime import datetime

from psycopg.errors import UniqueViolation

from app.core.normalization import limpa_codigo
from app.core.resource_mapping import resource_display_name


def _as_dict(row):
    return dict(row) if row else None


def _rows(cursor):
    return [dict(row) for row in cursor.fetchall()]


class QualityRepositoryMixin:
    # ------------------------------------------------------------------
    # Roteiro: a operação de inspeção projetada pelo ProductionOrder
    # ------------------------------------------------------------------
    def buscar_operacao_inspecao(self, codigo_op):
        """Retorna a operação de inspeção da OP, se o roteiro possuir uma."""

        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT operacao.*, pcp.quantidade, pcp.produto_codigo AS op_produto_codigo,
                       pcp.produto_descricao AS op_produto_descricao
                FROM catalogo_operacoes_op operacao
                JOIN catalogo_pcp_ops pcp ON pcp.codigo_op = operacao.codigo_op
                WHERE operacao.codigo_op = %s
                  AND operacao.inspecao_qualidade IS TRUE
                ORDER BY operacao.ordem, operacao.id
                LIMIT 1
                """,
                (limpa_codigo(codigo_op),),
            )
            return _as_dict(cursor.fetchone())

    def buscar_operacao_produtiva_anterior(self, codigo_op, ordem_inspecao):
        """Operação produtiva imediatamente anterior à inspeção."""

        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT operacao.*, recurso.nome AS recurso_nome,
                       recurso.tipo_setor AS recurso_tipo_setor
                FROM catalogo_operacoes_op operacao
                LEFT JOIN catalogo_recursos_pcfactory recurso
                  ON recurso.codigo = operacao.codigo_recurso
                WHERE operacao.codigo_op = %s
                  AND operacao.ativo IS TRUE
                  AND operacao.marco_terminal IS FALSE
                  AND operacao.inspecao_qualidade IS FALSE
                  AND operacao.ordem < %s
                ORDER BY operacao.ordem DESC, operacao.id DESC
                LIMIT 1
                """,
                (limpa_codigo(codigo_op), int(ordem_inspecao)),
            )
            return _as_dict(cursor.fetchone())

    def buscar_op_planejada(self, codigo_op):
        """Confirma se a OP existe LOCALMENTE. Nunca consulta o ERP.

        A Qualidade é sempre uma etapa posterior: quando o fluxo chega nela a OP
        já entrou pelo pipeline canônico do ProductionOrder. Por isso esta tela
        não possui busca sob demanda — ela apenas distingue "não existe aqui" de
        "existe, mas ainda não chegou na inspeção".
        """

        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT * FROM catalogo_pcp_ops WHERE codigo_op = %s",
                (limpa_codigo(codigo_op),),
            )
            return _as_dict(cursor.fetchone())

    def buscar_ultima_inspecao(self, codigo_op):
        """Última sessão de inspeção conhecida da OP, concluída ou não."""

        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT * FROM qualidade_inspecoes
                WHERE UPPER(codigo_op) = UPPER(%s)
                ORDER BY iniciada_em DESC, id DESC
                LIMIT 1
                """,
                (limpa_codigo(codigo_op),),
            )
            return _as_dict(cursor.fetchone())

    def listar_ops_elegiveis_inspecao(self, *, limite=200):
        """Fila da Qualidade: OPs cujo roteiro chegou na operação de inspeção.

        Elegível significa exatamente o estado do roteiro, lido da máquina de
        estados que já existe:

        * a OP possui operação de inspeção;
        * todas as operações apontáveis anteriores estão ``Finalizado``;
        * a própria operação de inspeção **não** está ``Finalizado``.

        Quem torna a inspeção elegível é a conclusão da etapa anterior, não um
        botão manual. Nenhuma segunda fonte de OP é criada e nada é consultado
        no ERP: tudo vem de ``catalogo_pcp_ops``, ``catalogo_operacoes_op`` e
        ``apontamentos_operacionais``.

        ``quantidade`` é o **saldo** a inspecionar: peças já aprovadas reduzem o
        planejado, e uma inspeção que terminou com retrabalho volta para a fila
        com o que ainda falta — a mesma regra de saldo de qualquer operação.
        """

        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                WITH inspecao AS (
                    SELECT DISTINCT ON (codigo_op)
                           id, codigo_op, numero_operacao, codigo_recurso,
                           descricao_operacao, produto_codigo, produto_descricao,
                           ordem, totvs_activity_id, totvs_work_center_code,
                           totvs_machine_code
                    FROM catalogo_operacoes_op
                    WHERE inspecao_qualidade IS TRUE
                    ORDER BY codigo_op, ordem, id
                ),
                dispensada AS (
                    -- Inspeção pulada pela regra transitória: sai da fila sem
                    -- nunca ter sido executada e sem virar aprovação.
                    SELECT DISTINCT UPPER(codigo_op) AS codigo_op
                    FROM qualidade_inspecoes
                    WHERE status = 'DISPENSADA'
                )
                SELECT
                    inspecao.id AS catalogo_operacao_id,
                    inspecao.codigo_op,
                    inspecao.numero_operacao,
                    inspecao.codigo_recurso,
                    inspecao.descricao_operacao,
                    inspecao.produto_codigo,
                    inspecao.produto_descricao,
                    GREATEST(
                        pcp.quantidade - COALESCE(execucao.quantidade_boa, 0), 0
                    ) AS quantidade,
                    pcp.quantidade AS quantidade_planejada,
                    COALESCE(execucao.quantidade_boa, 0) AS quantidade_aprovada,
                    pcp.data_liberacao,
                    pcp.inicio_planejado,
                    recurso.nome AS recurso_nome,
                    anteriores.total AS operacoes_anteriores,
                    anteriores.concluidas AS operacoes_anteriores_concluidas,
                    execucao.status AS status_apontamento,
                    sessao.id AS inspecao_id,
                    sessao.status AS inspecao_status,
                    COALESCE(sessao.pecas_registradas, 0) AS pecas_registradas,
                    origem.tipo_setor AS tipo_setor_origem,
                    origem.codigo_recurso AS codigo_recurso_origem
                FROM inspecao
                JOIN catalogo_pcp_ops pcp
                  ON pcp.codigo_op = inspecao.codigo_op AND pcp.ativo IS TRUE
                LEFT JOIN catalogo_recursos_pcfactory recurso
                  ON recurso.codigo = inspecao.codigo_recurso
                LEFT JOIN LATERAL (
                    SELECT
                        COUNT(*) AS total,
                        COUNT(*) FILTER (
                            WHERE (
                                EXISTS (
                                    SELECT 1 FROM apontamentos_operacionais ap
                                    WHERE ap.catalogo_operacao_id = anterior.id
                                      AND ap.status = 'Finalizado'
                                )
                                OR (
                                    UPPER(anterior.tipo_setor) = 'CORTE'
                                    AND EXISTS (
                                        SELECT 1
                                        FROM op_por_tarefa vinculo
                                        JOIN tarefas tarefa ON tarefa.id = vinculo.tarefa_id
                                        WHERE vinculo.codigo_op = anterior.codigo_op
                                          AND tarefa.status = 'Finalizado'
                                          AND EXISTS (
                                              SELECT 1
                                              FROM catalogo_sigmanest_planos_corte plano
                                              WHERE plano.codigo_tarefa = tarefa.codigo_tarefa
                                                AND plano.ativo IS TRUE
                                          )
                                          AND NOT EXISTS (
                                              SELECT 1
                                              FROM catalogo_sigmanest_planos_corte plano
                                              WHERE plano.codigo_tarefa = tarefa.codigo_tarefa
                                                AND plano.ativo IS TRUE
                                                AND NOT EXISTS (
                                                    SELECT 1
                                                    FROM apontamentos_corte corte
                                                    WHERE corte.plano_hash = plano.plano_hash
                                                      AND corte.status = 'Finalizado'
                                                )
                                          )
                                    )
                                )
                            )
                        ) AS concluidas
                    FROM catalogo_operacoes_op anterior
                    WHERE anterior.codigo_op = inspecao.codigo_op
                      AND anterior.ativo IS TRUE
                      AND anterior.marco_terminal IS FALSE
                      AND anterior.ordem < inspecao.ordem
                ) anteriores ON TRUE
                LEFT JOIN LATERAL (
                    SELECT ap.status, ap.quantidade_boa
                    FROM apontamentos_operacionais ap
                    WHERE ap.catalogo_operacao_id = inspecao.id
                    ORDER BY ap.data_entrada DESC, ap.id DESC
                    LIMIT 1
                ) execucao ON TRUE
                -- Setor dono da inspeção: a etapa apontável imediatamente
                -- anterior no roteiro, isto é, quem produziu a peça. A própria
                -- operação de inspeção entra do TOTVS sem ``tipo_setor``, então
                -- é daqui que sai a separação por setor da fila da Qualidade.
                LEFT JOIN LATERAL (
                    SELECT anterior.tipo_setor, anterior.codigo_recurso
                    FROM catalogo_operacoes_op anterior
                    WHERE anterior.codigo_op = inspecao.codigo_op
                      AND anterior.ativo IS TRUE
                      AND anterior.marco_terminal IS FALSE
                      AND anterior.inspecao_qualidade IS FALSE
                      AND anterior.ordem < inspecao.ordem
                      AND NULLIF(TRIM(anterior.tipo_setor), '') IS NOT NULL
                    ORDER BY anterior.ordem DESC, anterior.id DESC
                    LIMIT 1
                ) origem ON TRUE
                LEFT JOIN LATERAL (
                    SELECT s.id, s.status,
                           (
                               SELECT COUNT(*) FROM qualidade_pecas_inspecionadas p
                               WHERE p.inspecao_id = s.id
                           ) AS pecas_registradas
                    FROM qualidade_inspecoes s
                    WHERE UPPER(s.codigo_op) = UPPER(inspecao.codigo_op)
                      AND s.numero_operacao = inspecao.numero_operacao
                      AND s.status = 'EM_INSPECAO'
                    ORDER BY s.iniciada_em DESC, s.id DESC
                    LIMIT 1
                ) sessao ON TRUE
                WHERE COALESCE(execucao.status, '') <> 'Finalizado'
                  AND NOT EXISTS (
                      SELECT 1 FROM dispensada
                      WHERE dispensada.codigo_op = UPPER(inspecao.codigo_op)
                  )
                  AND GREATEST(
                      pcp.quantidade - COALESCE(execucao.quantidade_boa, 0), 0
                  ) > 0
                  AND COALESCE(anteriores.total, 0)
                      = COALESCE(anteriores.concluidas, 0)
                  AND NOT EXISTS (
                      SELECT 1
                      FROM apontamentos_operacionais retorno
                      WHERE UPPER(retorno.op) = UPPER(inspecao.codigo_op)
                        AND retorno.retorno_retrabalho_qualidade IS TRUE
                        AND retorno.status IN (
                            'Aguardando', 'Em processo', 'Parada', 'Setup', 'Retrabalho'
                        )
                  )
                ORDER BY pcp.inicio_planejado NULLS LAST, inspecao.codigo_op
                LIMIT %s
                """,
                (int(limite),),
            )
            return _rows(cursor)

    # ------------------------------------------------------------------
    # Template de cotas do produto
    # ------------------------------------------------------------------
    def buscar_template_qualidade(self, produto_codigo, *, somente_ativas=True):
        produto = str(produto_codigo or "").strip()
        if not produto:
            return None
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT * FROM qualidade_templates_produto WHERE produto_codigo = %s",
                (produto,),
            )
            template = _as_dict(cursor.fetchone())
            if template is None:
                return None
            query = "SELECT * FROM qualidade_cotas_template WHERE template_id = %s"
            if somente_ativas:
                query += " AND ativo IS TRUE"
            query += " ORDER BY ordem, sequencia, id"
            cursor.execute(query, (template["id"],))
            template["cotas"] = _rows(cursor)
            return template

    def salvar_template_qualidade(
        self,
        produto_codigo,
        cotas,
        *,
        produto_descricao=None,
        usuario_id=None,
        usuario_nome="",
        agora: datetime | None = None,
        nova_revisao=False,
    ):
        """Cria ou substitui o conjunto de cotas do produto de forma atômica.

        Cota removida é **inativada**, nunca apagada: inspeções históricas
        continuam apontando para a linha original, e o snapshot gravado na peça
        preserva o padrão realmente usado mesmo depois de uma edição.
        """

        produto = str(produto_codigo or "").strip()
        instante = agora or datetime.now().replace(microsecond=0)
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO qualidade_templates_produto (
                    produto_codigo, produto_descricao, revisao, ativo,
                    criado_por, criado_por_nome, atualizado_por,
                    atualizado_por_nome, criado_em, atualizado_em
                ) VALUES (%s, %s, 1, TRUE, %s, %s, %s, %s, %s, %s)
                ON CONFLICT ON CONSTRAINT uq_qualidade_template_produto DO UPDATE SET
                    produto_descricao = COALESCE(
                        EXCLUDED.produto_descricao,
                        qualidade_templates_produto.produto_descricao
                    ),
                    revisao = qualidade_templates_produto.revisao + CASE WHEN %s THEN 1 ELSE 0 END,
                    atualizado_por = EXCLUDED.atualizado_por,
                    atualizado_por_nome = EXCLUDED.atualizado_por_nome,
                    atualizado_em = EXCLUDED.atualizado_em
                RETURNING *
                """,
                (
                    produto,
                    str(produto_descricao or "").strip() or None,
                    usuario_id,
                    str(usuario_nome or "").strip() or "Operador",
                    usuario_id,
                    str(usuario_nome or "").strip() or "Operador",
                    instante,
                    instante,
                    bool(nova_revisao),
                ),
            )
            template = dict(cursor.fetchone())
            informadas = []
            for ordem, cota in enumerate(cotas or (), start=1):
                sequencia = int(cota.get("sequencia") or ordem)
                cursor.execute(
                    """
                    INSERT INTO qualidade_cotas_template (
                        template_id, sequencia, descricao, padrao, unidade,
                        ordem, ativo, criado_em, atualizado_em
                    ) VALUES (%s, %s, %s, %s, %s, %s, TRUE, %s, %s)
                    ON CONFLICT ON CONSTRAINT uq_qualidade_cota_sequencia DO UPDATE SET
                        descricao = EXCLUDED.descricao,
                        padrao = EXCLUDED.padrao,
                        unidade = EXCLUDED.unidade,
                        ordem = EXCLUDED.ordem,
                        ativo = TRUE,
                        atualizado_em = EXCLUDED.atualizado_em
                    RETURNING id
                    """,
                    (
                        template["id"],
                        sequencia,
                        str(cota.get("descricao") or "").strip() or None,
                        str(cota.get("padrao") or "").strip(),
                        str(cota.get("unidade") or "").strip() or None,
                        ordem,
                        instante,
                        instante,
                    ),
                )
                informadas.append(sequencia)
            cursor.execute(
                """
                UPDATE qualidade_cotas_template
                SET ativo = FALSE, atualizado_em = %s
                WHERE template_id = %s
                  AND ativo IS TRUE
                  AND NOT (sequencia = ANY(%s))
                """,
                (instante, template["id"], informadas or [0]),
            )
            cursor.execute(
                """
                SELECT * FROM qualidade_cotas_template
                WHERE template_id = %s AND ativo IS TRUE
                ORDER BY ordem, sequencia, id
                """,
                (template["id"],),
            )
            template["cotas"] = _rows(cursor)
            return template

    # ------------------------------------------------------------------
    # Sessão de inspeção
    # ------------------------------------------------------------------
    def abrir_inspecao_qualidade(self, **valores):
        """Abre a sessão de inspeção; devolve ``None`` quando já existe outra."""

        instante = valores.get("iniciada_em") or datetime.now().replace(microsecond=0)
        try:
            with self.connection() as connection, connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO qualidade_inspecoes (
                        codigo_op, catalogo_operacao_id, apontamento_id,
                        numero_operacao, produto_codigo, produto_descricao,
                        tipo_setor, tipo_setor_origem, codigo_recurso,
                        quantidade_total, template_id, template_revisao,
                        status, operador, iniciada_em
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        'EM_INSPECAO', %s, %s
                    )
                    RETURNING *
                    """,
                    (
                        limpa_codigo(valores.get("codigo_op")),
                        valores.get("catalogo_operacao_id"),
                        valores.get("apontamento_id"),
                        str(valores.get("numero_operacao") or "").strip(),
                        str(valores.get("produto_codigo") or "").strip(),
                        str(valores.get("produto_descricao") or "").strip() or None,
                        str(valores.get("tipo_setor") or "").strip(),
                        str(valores.get("tipo_setor_origem") or "").strip() or None,
                        str(valores.get("codigo_recurso") or "").strip(),
                        int(valores.get("quantidade_total") or 1),
                        valores.get("template_id"),
                        valores.get("template_revisao"),
                        str(valores.get("operador") or "Operador").strip(),
                        instante,
                    ),
                )
                return dict(cursor.fetchone())
        except UniqueViolation:
            return None

    def dispensar_inspecao_qualidade(self, **valores):
        """Registra que a inspeção foi **pulada**, não que ela aconteceu.

        A sessão nasce em estado terminal ``DISPENSADA`` e o banco recusa
        qualquer falsificação: sem apontamento, sem template e sem peça. Cotas,
        RNC e resultado continuam inexistentes — não houve inspeção. O que
        existe é a decisão, com autor, crachá e horário.
        """

        instante = valores.get("dispensada_em") or datetime.now().replace(microsecond=0)
        try:
            with self.connection() as connection, connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO qualidade_inspecoes (
                        codigo_op, catalogo_operacao_id, apontamento_id,
                        numero_operacao, produto_codigo, produto_descricao,
                        tipo_setor, tipo_setor_origem, codigo_recurso,
                        quantidade_total, template_id, template_revisao,
                        status, operador, iniciada_em, finalizada_em,
                        dispensa_motivo, dispensa_autorizada_por,
                        dispensa_cracha
                    ) VALUES (
                        %s, %s, NULL, %s, %s, %s, %s, %s, %s, %s, NULL, NULL,
                        'DISPENSADA', %s, %s, %s, %s, %s, %s
                    )
                    RETURNING *
                    """,
                    (
                        limpa_codigo(valores.get("codigo_op")),
                        valores.get("catalogo_operacao_id"),
                        str(valores.get("numero_operacao") or "").strip(),
                        str(valores.get("produto_codigo") or "").strip(),
                        str(valores.get("produto_descricao") or "").strip() or None,
                        str(valores.get("tipo_setor") or "").strip(),
                        str(valores.get("tipo_setor_origem") or "").strip() or None,
                        str(valores.get("codigo_recurso") or "").strip(),
                        max(1, int(valores.get("quantidade_total") or 1)),
                        str(valores.get("operador") or "Operador").strip(),
                        instante,
                        instante,
                        str(valores.get("motivo") or "").strip() or None,
                        str(valores.get("autorizada_por") or "").strip(),
                        str(valores.get("cracha") or "").strip() or None,
                    ),
                )
                return dict(cursor.fetchone())
        except UniqueViolation:
            return None

    def buscar_dispensa_inspecao(self, codigo_op, numero_operacao=None):
        """Última dispensa registrada para a OP, se houver."""

        query = """
            SELECT * FROM qualidade_inspecoes
            WHERE UPPER(codigo_op) = UPPER(%s) AND status = 'DISPENSADA'
        """
        params = [limpa_codigo(codigo_op)]
        if numero_operacao:
            query += " AND numero_operacao = %s"
            params.append(str(numero_operacao).strip())
        query += " ORDER BY finalizada_em DESC, id DESC LIMIT 1"
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(query, params)
            linha = cursor.fetchone()
            return dict(linha) if linha else None

    def buscar_inspecao_qualidade(self, inspecao_id):
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT * FROM qualidade_inspecoes WHERE id = %s", (int(inspecao_id),)
            )
            return _as_dict(cursor.fetchone())

    def buscar_inspecao_aberta(self, codigo_op, numero_operacao):
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT * FROM qualidade_inspecoes
                WHERE UPPER(codigo_op) = UPPER(%s)
                  AND numero_operacao = %s
                  AND status = 'EM_INSPECAO'
                ORDER BY iniciada_em DESC, id DESC
                LIMIT 1
                """,
                (limpa_codigo(codigo_op), str(numero_operacao or "").strip()),
            )
            return _as_dict(cursor.fetchone())

    def concluir_inspecao_qualidade(self, inspecao_id, *, finalizada_em=None):
        instante = finalizada_em or datetime.now().replace(microsecond=0)
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE qualidade_inspecoes
                SET status = 'CONCLUIDA', finalizada_em = %s
                WHERE id = %s AND status = 'EM_INSPECAO'
                RETURNING *
                """,
                (instante, int(inspecao_id)),
            )
            return _as_dict(cursor.fetchone())

    def vincular_apontamento_inspecao(self, inspecao_id, apontamento_id):
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE qualidade_inspecoes SET apontamento_id = %s
                WHERE id = %s
                RETURNING *
                """,
                (apontamento_id, int(inspecao_id)),
            )
            return _as_dict(cursor.fetchone())

    def listar_pecas_inspecionadas(self, inspecao_id):
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT peca.*, rnc.codigo AS rnc_codigo
                FROM qualidade_pecas_inspecionadas peca
                LEFT JOIN qualidade_rnc rnc ON rnc.id = peca.rnc_id
                WHERE peca.inspecao_id = %s
                ORDER BY peca.numero_peca
                """,
                (int(inspecao_id),),
            )
            return _rows(cursor)

    def registrar_peca_inspecionada(
        self,
        inspecao_id,
        *,
        numero_peca,
        resultado,
        possui_nao_conformidade,
        operador,
        cotas,
        rnc=None,
        operacao_retrabalho=None,
        registrada_em=None,
    ):
        """Grava peça, cotas e RNC na MESMA transação.

        Uma peça com cota não conforme sem a RNC correspondente seria um
        registro de qualidade incompleto e não auditável; por isso a RNC nasce
        aqui, junto, e não em uma segunda chamada que pode falhar sozinha.
        Devolve ``None`` quando a unidade já foi registrada — é a proteção
        contra dois operadores apontando a mesma peça.
        """

        instante = registrada_em or datetime.now().replace(microsecond=0)
        try:
            with self.connection() as connection, connection.cursor() as cursor:
                cursor.execute(
                    "SELECT * FROM qualidade_inspecoes WHERE id = %s FOR UPDATE",
                    (int(inspecao_id),),
                )
                sessao = _as_dict(cursor.fetchone())
                if sessao is None or sessao.get("status") != "EM_INSPECAO":
                    return None
                rnc_id = None
                rnc_row = None
                if rnc:
                    cursor.execute(
                        """
                        INSERT INTO qualidade_rnc (
                            codigo, inspecao_id, numero_peca, codigo_op,
                            produto_codigo, tipo_setor, codigo_recurso,
                            operador, motivo, observacao, registrada_em
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        RETURNING *
                        """,
                        (
                            str(rnc.get("codigo") or "").strip(),
                            int(inspecao_id),
                            int(numero_peca),
                            sessao["codigo_op"],
                            sessao["produto_codigo"],
                            sessao["tipo_setor"],
                            sessao["codigo_recurso"],
                            str(operador or "Operador").strip(),
                            str(rnc.get("motivo") or "").strip(),
                            str(rnc.get("observacao") or "").strip() or None,
                            instante,
                        ),
                    )
                    rnc_row = dict(cursor.fetchone())
                    rnc_id = rnc_row["id"]
                cursor.execute(
                    """
                    INSERT INTO qualidade_pecas_inspecionadas (
                        inspecao_id, numero_peca, resultado,
                        possui_nao_conformidade, rnc_id, operador, registrada_em
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                    RETURNING *
                    """,
                    (
                        int(inspecao_id),
                        int(numero_peca),
                        str(resultado or "").strip().upper(),
                        bool(possui_nao_conformidade),
                        rnc_id,
                        str(operador or "Operador").strip(),
                        instante,
                    ),
                )
                peca = dict(cursor.fetchone())
                for cota in cotas or ():
                    cursor.execute(
                        """
                        INSERT INTO qualidade_resultados_cota (
                            peca_id, cota_template_id, sequencia,
                            descricao_snapshot, padrao_snapshot,
                            unidade_snapshot, medida, status
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            peca["id"],
                            cota.get("cota_template_id"),
                            int(cota.get("sequencia") or 0),
                            str(cota.get("descricao") or "").strip() or None,
                            str(cota.get("padrao") or "").strip(),
                            str(cota.get("unidade") or "").strip() or None,
                            str(cota.get("medida") or "").strip(),
                            str(cota.get("status") or "").strip().upper(),
                        ),
                    )
                if str(resultado or "").strip().upper() == "RETRABALHO":
                    anterior = dict(operacao_retrabalho or {})
                    if not anterior:
                        raise ValueError(
                            "O roteiro não possui operação produtiva anterior para o retrabalho."
                        )
                    cursor.execute(
                        """
                        SELECT * FROM apontamentos_operacionais
                        WHERE origem_retrabalho_inspecao_id = %s
                          AND catalogo_operacao_id = %s
                          AND retorno_retrabalho_qualidade IS TRUE
                          AND status IN (
                              'Aguardando', 'Em processo', 'Parada', 'Setup', 'Retrabalho'
                          )
                        ORDER BY id DESC
                        LIMIT 1
                        FOR UPDATE
                        """,
                        (int(inspecao_id), anterior.get("id")),
                    )
                    retorno = _as_dict(cursor.fetchone())
                    if retorno is None:
                        codigo_recurso = str(
                            anterior.get("codigo_recurso") or ""
                        ).strip()
                        maquina = resource_display_name(
                            codigo_recurso, anterior.get("recurso_nome")
                        )
                        cursor.execute(
                            """
                            SELECT tarefa_id FROM op_por_tarefa
                            WHERE codigo_op = %s ORDER BY id LIMIT 1
                            """,
                            (sessao["codigo_op"],),
                        )
                        vinculo = cursor.fetchone()
                        cursor.execute(
                            """
                            INSERT INTO apontamentos_operacionais (
                                op, peca, tarefa_id, tipo_setor, maquina, status,
                                quantidade, operador_fila, data_entrada,
                                catalogo_operacao_id, numero_operacao,
                                codigo_recurso, descricao_operacao,
                                produto_codigo, produto_descricao,
                                retorno_retrabalho_qualidade,
                                origem_retrabalho_inspecao_id
                            ) VALUES (
                                %s, %s, %s, %s, %s, 'Aguardando', 1, %s, %s,
                                %s, %s, %s, %s, %s, %s, TRUE, %s
                            )
                            RETURNING *
                            """,
                            (
                                sessao["codigo_op"],
                                sessao.get("produto_codigo") or "",
                                (vinculo or {}).get("tarefa_id"),
                                anterior.get("tipo_setor"),
                                maquina or codigo_recurso,
                                str(operador or "Operador").strip(),
                                instante,
                                anterior.get("id"),
                                anterior.get("numero_operacao"),
                                codigo_recurso,
                                anterior.get("descricao_operacao"),
                                anterior.get("produto_codigo")
                                or sessao.get("produto_codigo"),
                                anterior.get("produto_descricao")
                                or sessao.get("produto_descricao"),
                                int(inspecao_id),
                            ),
                        )
                        retorno = dict(cursor.fetchone())
                        cursor.execute(
                            """
                            INSERT INTO eventos_apontamento_operador (
                                apontamento_id, estado, comentario, operador, data_hora
                            ) VALUES (%s, 'fila', %s, %s, %s)
                            """,
                            (
                                retorno["id"],
                                f"Retrabalho originado pela inspeção {inspecao_id}, peça {numero_peca}",
                                str(operador or "Operador").strip(),
                                instante,
                            ),
                        )
                    else:
                        cursor.execute(
                            """
                            UPDATE apontamentos_operacionais
                            SET quantidade = quantidade + 1
                            WHERE id = %s
                            RETURNING *
                            """,
                            (retorno["id"],),
                        )
                        retorno = dict(cursor.fetchone())
                    cursor.execute(
                        """
                        UPDATE qualidade_pecas_inspecionadas
                        SET retrabalho_apontamento_id = %s
                        WHERE id = %s
                        """,
                        (retorno["id"], peca["id"]),
                    )
                    peca["retrabalho_apontamento_id"] = retorno["id"]
                peca["rnc"] = rnc_row
                return peca
        except UniqueViolation:
            return None

    def listar_resultados_cota(self, peca_id):
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT * FROM qualidade_resultados_cota
                WHERE peca_id = %s ORDER BY sequencia
                """,
                (int(peca_id),),
            )
            return _rows(cursor)

    def buscar_inspecao_da_peca(self, peca_id):
        """Inspeção dona de uma peça, para revalidar o recorte de setor na leitura."""

        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT s.* FROM qualidade_pecas_inspecionadas p
                JOIN qualidade_inspecoes s ON s.id = p.inspecao_id
                WHERE p.id = %s
                """,
                (int(peca_id),),
            )
            return _as_dict(cursor.fetchone())

    # Setor de origem de uma inspeção já aberta. A sessão passou a **gravar** a
    # origem na abertura (é o que permite revalidar o recorte de setor na
    # escrita); a derivação pelo roteiro fica como retaguarda das linhas
    # anteriores à migração cujo vínculo de catálogo já não resolve.
    _SETOR_ORIGEM_SQL = """COALESCE(NULLIF(TRIM(s.tipo_setor_origem), ''), (
        SELECT anterior.tipo_setor
        FROM catalogo_operacoes_op inspecao
        JOIN catalogo_operacoes_op anterior
          ON anterior.codigo_op = inspecao.codigo_op
         AND anterior.ativo IS TRUE
         AND anterior.marco_terminal IS FALSE
         AND anterior.inspecao_qualidade IS FALSE
         AND anterior.ordem < inspecao.ordem
         AND NULLIF(TRIM(anterior.tipo_setor), '') IS NOT NULL
        WHERE inspecao.id = s.catalogo_operacao_id
        ORDER BY anterior.ordem DESC, anterior.id DESC
        LIMIT 1
    ))"""

    def resumo_qualidade(self, *, setor=None, setor_origem=None):
        """Contadores da tela: aguardando inspeção, aprovadas, retrabalho e refugo.

        ``setor`` recorta pelo setor do apontamento (sempre ``Qualidade``);
        ``setor_origem`` recorta pelo setor que produziu a peça, que é o que
        separa a Qualidade da Dobra da Qualidade da Usinagem.
        """

        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    COALESCE(SUM(
                        GREATEST(inspecao.quantidade_total - inspecao.registradas, 0)
                    ), 0) AS aguardando,
                    COALESCE(SUM(inspecao.aprovadas), 0) AS aprovadas,
                    COALESCE(SUM(inspecao.retrabalho), 0) AS retrabalho,
                    COALESCE(SUM(inspecao.refugo), 0) AS refugo
                FROM (
                    SELECT
                        s.quantidade_total,
                        COUNT(p.id) AS registradas,
                        COUNT(p.id) FILTER (WHERE p.resultado = 'APROVADA') AS aprovadas,
                        COUNT(p.id) FILTER (WHERE p.resultado = 'RETRABALHO') AS retrabalho,
                        COUNT(p.id) FILTER (WHERE p.resultado = 'REFUGO') AS refugo
                    FROM qualidade_inspecoes s
                    LEFT JOIN qualidade_pecas_inspecionadas p ON p.inspecao_id = s.id
                    WHERE (%(setor)s::TEXT IS NULL OR UPPER(s.tipo_setor) = UPPER(%(setor)s::TEXT))
                      AND (
                        %(setor_origem)s::TEXT IS NULL
                        OR {_SETOR_ORIGEM_SQL} IS NULL
                        OR UPPER({_SETOR_ORIGEM_SQL}) = UPPER(%(setor_origem)s::TEXT)
                      )
                    GROUP BY s.id, s.quantidade_total
                ) inspecao
                """.replace("{_SETOR_ORIGEM_SQL}", self._SETOR_ORIGEM_SQL),  # nosec B608 -- string SQL sem interpolação de variável (não é nem f-string)
                {"setor": setor, "setor_origem": setor_origem},
            )
            return _as_dict(cursor.fetchone()) or {}

    def contar_pendentes_inspecao(self):
        """Peças ainda não inspecionadas nas OPs elegíveis sem sessão aberta."""

        elegiveis = self.listar_ops_elegiveis_inspecao(limite=1000)
        return sum(
            max(int(item.get("quantidade") or 0) - int(item.get("pecas_registradas") or 0), 0)
            for item in elegiveis
        )

    def listar_historico_qualidade(
        self,
        *,
        setor=None,
        setor_origem=None,
        inicio=None,
        fim=None,
        op=None,
        produto=None,
        recurso=None,
        resultado=None,
        limite=200,
        deslocamento=0,
    ):
        clauses = [
            "(%(setor)s::TEXT IS NULL OR UPPER(s.tipo_setor) = UPPER(%(setor)s::TEXT))",
            (
                "(%(setor_origem)s::TEXT IS NULL"
                f" OR {self._SETOR_ORIGEM_SQL} IS NULL"
                f" OR UPPER({self._SETOR_ORIGEM_SQL}) = UPPER(%(setor_origem)s::TEXT))"
            ),
        ]
        params = {
            "setor": setor,
            "setor_origem": setor_origem,
            "inicio": inicio,
            "fim": fim,
            "op": str(op or "").strip() or None,
            "produto": str(produto or "").strip() or None,
            "recurso": str(recurso or "").strip() or None,
            "resultado": str(resultado or "").strip().upper() or None,
            "limite": int(limite),
            "deslocamento": int(deslocamento),
        }
        clauses.append(
            "(%(inicio)s::TIMESTAMP IS NULL OR p.registrada_em >= %(inicio)s::TIMESTAMP)"
        )
        clauses.append(
            "(%(fim)s::TIMESTAMP IS NULL OR p.registrada_em <= %(fim)s::TIMESTAMP)"
        )
        clauses.append(
            "(%(op)s::TEXT IS NULL OR UPPER(s.codigo_op) LIKE UPPER(%(op)s::TEXT) || '%%')"
        )
        clauses.append(
            "(%(produto)s::TEXT IS NULL"
            " OR UPPER(s.produto_codigo) LIKE UPPER(%(produto)s::TEXT) || '%%')"
        )
        clauses.append(
            "(%(recurso)s::TEXT IS NULL"
            " OR UPPER(s.codigo_recurso) = UPPER(%(recurso)s::TEXT))"
        )
        clauses.append(
            "(%(resultado)s::TEXT IS NULL OR p.resultado = %(resultado)s::TEXT)"
        )
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT
                    p.id AS peca_id,
                    p.numero_peca,
                    p.resultado,
                    p.registrada_em,
                    p.operador,
                    p.possui_nao_conformidade,
                    rnc.codigo AS rnc_codigo,
                    rnc.motivo AS rnc_motivo,
                    s.id AS inspecao_id,
                    s.codigo_op,
                    s.numero_operacao,
                    s.produto_codigo,
                    s.produto_descricao,
                    s.codigo_recurso,
                    s.tipo_setor,
                    s.quantidade_total
                FROM qualidade_pecas_inspecionadas p
                JOIN qualidade_inspecoes s ON s.id = p.inspecao_id
                LEFT JOIN qualidade_rnc rnc ON rnc.id = p.rnc_id
                WHERE {' AND '.join(clauses)}
                ORDER BY p.registrada_em DESC, p.id DESC
                LIMIT %(limite)s OFFSET %(deslocamento)s
                """,  # nosec B608 -- colunas vêm de constante do módulo, valores via %(...)s
                params,
            )
            return _rows(cursor)

    # ------------------------------------------------------------------
    # Desenho/PDF do produto
    # ------------------------------------------------------------------
    def buscar_desenho_produto(self, produto_codigo):
        """Regra canônica de 'mais recente': maior versão ativa do produto."""

        produto = str(produto_codigo or "").strip()
        if not produto:
            return None
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT * FROM qualidade_desenhos_produto
                WHERE produto_codigo = %s AND ativo IS TRUE
                ORDER BY versao DESC, enviado_em DESC, id DESC
                LIMIT 1
                """,
                (produto,),
            )
            return _as_dict(cursor.fetchone())

    def registrar_desenho_produto(self, **valores):
        produto = str(valores.get("produto_codigo") or "").strip()
        instante = valores.get("enviado_em") or datetime.now().replace(microsecond=0)
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT COALESCE(MAX(versao), 0) AS versao
                FROM qualidade_desenhos_produto WHERE produto_codigo = %s
                """,
                (produto,),
            )
            versao = int((cursor.fetchone() or {}).get("versao") or 0) + 1
            cursor.execute(
                """
                INSERT INTO qualidade_desenhos_produto (
                    produto_codigo, versao, filename, storage_path, content_type,
                    size_bytes, paginas, enviado_por, enviado_por_nome,
                    enviado_em, ativo
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, TRUE)
                RETURNING *
                """,
                (
                    produto,
                    versao,
                    str(valores.get("filename") or "").strip(),
                    str(valores.get("storage_path") or "").strip(),
                    str(valores.get("content_type") or "application/pdf").strip(),
                    int(valores.get("size_bytes") or 0),
                    valores.get("paginas"),
                    valores.get("enviado_por"),
                    str(valores.get("enviado_por_nome") or "").strip() or "Sistema",
                    instante,
                ),
            )
            return dict(cursor.fetchone())
