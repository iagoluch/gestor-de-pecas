"""Read model dos fatos canônicos usados pelo outbound TOTVS controlado."""

from __future__ import annotations

from decimal import Decimal

from contextlib import contextmanager

from mes.integrations.totvs.outbound_models import (
    CanonicalExecutionEvent,
    CanonicalTerminalMilestone,
)


class TotvsOutboundRepositoryMixin:
    @contextmanager
    def _outbound_cursor(self, cursor=None):
        """Reaproveita o cursor da transação em curso quando houver um.

        O enqueue da outbox acontece dentro da MESMA transação que grava o fato
        canônico. Uma conexão nova não enxergaria as linhas ainda não
        commitadas, então o read model precisa aceitar o cursor de fora. Sem
        cursor, o comportamento anterior é preservado: conexão própria e
        somente leitura.
        """

        if cursor is not None:
            yield cursor
            return
        with self.connection() as connection, connection.cursor() as own:
            yield own

    def buscar_evento_canonico_outbound_totvs(
        self, evento_id: int, *, cursor=None
    ) -> CanonicalExecutionEvent | None:
        """Lê um fato já confirmado; não altera o fluxo canônico do operador."""

        with self._outbound_cursor(cursor) as cursor:
            cursor.execute(
                """
                SELECT
                    e.id AS event_id,
                    e.apontamento_id AS appointment_id,
                    e.estado,
                    e.data_hora AS event_time,
                    e.motivo AS event_reason,
                    e.codigo_status_recurso AS resource_status_code,
                    e.operador AS operator_code,
                    e.recurso_divergente AS resource_divergent,
                    a.op AS production_order,
                    a.numero_operacao AS operation,
                    o.totvs_activity_id AS activity_id,
                    o.totvs_machine_code AS resource_code,
                    a.produto_codigo AS item_code,
                    a.produto_descricao AS item_description,
                    p.local_estoque AS warehouse_code,
                    p.totvs_company_id AS company_id,
                    p.totvs_branch_id AS branch_id,
                    p.quantidade AS planned_quantity,
                    a.quantidade_boa AS accumulated_good_quantity,
                    COALESCE(q.good_quantity, 0) AS good_quantity,
                    COALESCE(q.scrap_quantity, 0) AS scrap_quantity,
                    COALESCE(q.rework_quantity, 0) AS rework_quantity,
                    q.scrap_reason,
                    COALESCE(segment.started_at, a.data_inicio, e.data_hora) AS execution_started_at,
                    previous.estado AS previous_state,
                    previous.data_hora AS previous_event_time,
                    previous.motivo AS previous_reason,
                    previous.codigo_status_recurso AS previous_resource_status_code,
                    previous.interrupcao_programada AS previous_interruption_planned
                FROM eventos_apontamento_operador e
                JOIN apontamentos_operacionais a ON a.id = e.apontamento_id
                LEFT JOIN catalogo_operacoes_op o ON o.id = a.catalogo_operacao_id
                LEFT JOIN catalogo_pcp_ops p ON p.codigo_op = a.op
                LEFT JOIN LATERAL (
                    SELECT
                        SUM(quantidade) FILTER (WHERE tipo = 'boa') AS good_quantity,
                        SUM(quantidade) FILTER (WHERE tipo = 'refugo') AS scrap_quantity,
                        SUM(quantidade) FILTER (WHERE tipo = 'retrabalho') AS rework_quantity,
                        MAX(motivo) FILTER (WHERE tipo = 'refugo') AS scrap_reason
                    FROM eventos_quantidade_producao
                    WHERE referencia_origem = 'evento_apontamento:' || e.id::TEXT
                ) q ON TRUE
                LEFT JOIN LATERAL (
                    SELECT prior.*
                    FROM eventos_apontamento_operador prior
                    WHERE prior.apontamento_id = e.apontamento_id
                      AND (prior.data_hora, prior.id) < (e.data_hora, e.id)
                    ORDER BY prior.data_hora DESC, prior.id DESC
                    LIMIT 1
                ) previous ON TRUE
                LEFT JOIN LATERAL (
                    SELECT prior.data_hora AS started_at
                    FROM eventos_apontamento_operador prior
                    WHERE prior.apontamento_id = e.apontamento_id
                      AND prior.estado IN ('producao', 'retrabalho')
                      AND (prior.data_hora, prior.id) <= (e.data_hora, e.id)
                    ORDER BY prior.data_hora DESC, prior.id DESC
                    LIMIT 1
                ) segment ON TRUE
                WHERE e.id = %s
                """,
                (int(evento_id),),
            )
            row = cursor.fetchone()
        if row is None:
            return None
        return CanonicalExecutionEvent(
            event_id=int(row["event_id"]),
            appointment_id=int(row["appointment_id"]),
            state=str(row["estado"]),
            event_time=row["event_time"],
            production_order=str(row["production_order"] or ""),
            operation=str(row["operation"] or ""),
            activity_id=str(row["activity_id"] or ""),
            resource_code=str(row["resource_code"] or ""),
            item_code=str(row["item_code"] or ""),
            item_description=row["item_description"],
            warehouse_code=row["warehouse_code"],
            company_id=str(row["company_id"] or ""),
            branch_id=str(row["branch_id"] or ""),
            operator_code=row["operator_code"],
            good_quantity=Decimal(row["good_quantity"] or 0),
            scrap_quantity=Decimal(row["scrap_quantity"] or 0),
            rework_quantity=Decimal(row["rework_quantity"] or 0),
            planned_quantity=Decimal(row["planned_quantity"] or 0),
            accumulated_good_quantity=Decimal(row["accumulated_good_quantity"] or 0),
            event_reason=row["event_reason"],
            scrap_reason=row["scrap_reason"],
            resource_status_code=row["resource_status_code"],
            execution_started_at=row["execution_started_at"],
            previous_state=row["previous_state"],
            previous_event_time=row["previous_event_time"],
            previous_reason=row["previous_reason"],
            previous_resource_status_code=row["previous_resource_status_code"],
            previous_interruption_planned=row["previous_interruption_planned"],
            resource_divergent=bool(row["resource_divergent"]),
        )

    def buscar_marco_terminal_outbound_totvs(
        self, codigo_op: str, *, cursor=None
    ) -> CanonicalTerminalMilestone | None:
        """Lê o marco terminal do roteiro e o resultado real já concluído.

        Somente SELECT. A conclusão é lida da máquina de estados do operador
        (último evento de cada operação apontável) e as quantidades vêm de
        ``eventos_quantidade_producao``, a fonte canônica. Operações
        intermediárias não são somadas: o que a OP entrega é o resultado da
        última operação produtiva.
        """

        with self._outbound_cursor(cursor) as cursor:
            cursor.execute(
                """
                WITH terminal AS (
                    SELECT numero_operacao, codigo_recurso, totvs_activity_id,
                           totvs_machine_code, ordem
                    FROM catalogo_operacoes_op
                    WHERE codigo_op = %(op)s AND marco_terminal IS TRUE
                    ORDER BY ordem DESC, numero_operacao DESC
                    LIMIT 1
                ),
                apontaveis AS (
                    SELECT id, numero_operacao, ordem
                    FROM catalogo_operacoes_op
                    WHERE codigo_op = %(op)s
                      AND ativo IS TRUE
                      AND marco_terminal IS FALSE
                ),
                ultimo_evento AS (
                    SELECT DISTINCT ON (a.numero_operacao)
                           a.numero_operacao,
                           e.estado,
                           e.data_hora,
                           e.operador,
                           e.recurso_divergente
                    FROM apontamentos_operacionais a
                    JOIN apontaveis c ON c.id = a.catalogo_operacao_id
                    JOIN eventos_apontamento_operador e ON e.apontamento_id = a.id
                    WHERE a.op = %(op)s
                    ORDER BY a.numero_operacao, e.data_hora DESC, e.id DESC
                ),
                ultima_produtiva AS (
                    SELECT c.numero_operacao
                    FROM apontaveis c
                    ORDER BY c.ordem DESC, c.numero_operacao DESC
                    LIMIT 1
                ),
                quantidades AS (
                    SELECT
                        SUM(q.quantidade) FILTER (WHERE q.tipo = 'boa') AS boa,
                        SUM(q.quantidade) FILTER (WHERE q.tipo = 'refugo') AS refugo,
                        SUM(q.quantidade) FILTER (WHERE q.tipo = 'retrabalho') AS retrabalho
                    FROM eventos_quantidade_producao q
                    JOIN ultima_produtiva u ON u.numero_operacao = q.numero_operacao
                    WHERE q.op = %(op)s
                ),
                execucao AS (
                    SELECT
                        MIN(e.data_hora) FILTER (WHERE e.estado IN ('producao', 'setup')) AS iniciada_em,
                        MAX(e.data_hora) FILTER (WHERE e.estado = 'finalizado') AS finalizada_em
                    FROM apontamentos_operacionais a
                    JOIN ultima_produtiva u ON u.numero_operacao = a.numero_operacao
                    JOIN eventos_apontamento_operador e ON e.apontamento_id = a.id
                    WHERE a.op = %(op)s
                )
                SELECT
                    p.codigo_op,
                    p.produto_codigo,
                    p.produto_descricao,
                    p.local_estoque,
                    p.totvs_company_id,
                    p.totvs_branch_id,
                    p.quantidade AS planned_quantity,
                    t.numero_operacao AS terminal_operation,
                    COALESCE(NULLIF(t.totvs_machine_code, ''), t.codigo_recurso) AS terminal_resource,
                    t.totvs_activity_id AS terminal_activity_id,
                    u.numero_operacao AS last_operation,
                    COALESCE(q.boa, 0) AS boa,
                    COALESCE(q.refugo, 0) AS refugo,
                    COALESCE(q.retrabalho, 0) AS retrabalho,
                    x.iniciada_em,
                    x.finalizada_em,
                    (SELECT COUNT(*) FROM apontaveis) AS apontaveis,
                    (SELECT COUNT(*) FROM ultimo_evento WHERE estado = 'finalizado') AS concluidas,
                    (
                        SELECT COALESCE(ARRAY_AGG(numero_operacao ORDER BY numero_operacao), ARRAY[]::TEXT[])
                        FROM apontaveis
                        WHERE numero_operacao NOT IN (
                            SELECT numero_operacao FROM ultimo_evento WHERE estado = 'finalizado'
                        )
                    ) AS em_aberto,
                    COALESCE(
                        (SELECT BOOL_OR(recurso_divergente) FROM ultimo_evento), FALSE
                    ) AS divergente,
                    (
                        SELECT operador FROM ultimo_evento
                        WHERE estado = 'finalizado'
                        ORDER BY data_hora DESC
                        LIMIT 1
                    ) AS operador
                FROM catalogo_pcp_ops p
                CROSS JOIN terminal t
                CROSS JOIN ultima_produtiva u
                CROSS JOIN quantidades q
                CROSS JOIN execucao x
                WHERE p.codigo_op = %(op)s
                """,
                {"op": str(codigo_op)},
            )
            row = cursor.fetchone()
        if row is None:
            return None
        return CanonicalTerminalMilestone(
            production_order=str(row["codigo_op"]),
            item_code=str(row["produto_codigo"] or ""),
            item_description=row["produto_descricao"],
            warehouse_code=row["local_estoque"],
            company_id=str(row["totvs_company_id"] or ""),
            branch_id=str(row["totvs_branch_id"] or ""),
            planned_quantity=Decimal(row["planned_quantity"] or 0),
            terminal_operation=str(row["terminal_operation"] or ""),
            terminal_resource_code=str(row["terminal_resource"] or ""),
            terminal_activity_id=row["terminal_activity_id"],
            last_operation=str(row["last_operation"] or ""),
            last_operation_good_quantity=Decimal(row["boa"] or 0),
            last_operation_scrap_quantity=Decimal(row["refugo"] or 0),
            last_operation_rework_quantity=Decimal(row["retrabalho"] or 0),
            execution_started_at=row["iniciada_em"],
            execution_finished_at=row["finalizada_em"],
            operator_code=row["operador"],
            pointable_operations=int(row["apontaveis"] or 0),
            concluded_operations=int(row["concluidas"] or 0),
            open_operations=tuple(str(item) for item in (row["em_aberto"] or ())),
            resource_divergent=bool(row["divergente"]),
        )
