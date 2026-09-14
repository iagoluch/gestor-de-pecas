"""Persistência incremental e transacional da integração TOTVS ProductionOrder."""

from __future__ import annotations

from datetime import datetime

from psycopg.types.json import Jsonb

from mes.integrations.totvs.errors import (
    TotvsIdentityConflictError,
    TotvsStoredMessageError,
    TotvsTemporalConflictError,
)


def _now() -> datetime:
    return datetime.now().replace(microsecond=0)


class TotvsRepositoryMixin:
    """Métodos PostgreSQL usados somente pelo caso de uso de ingestão TOTVS."""

    def registrar_mensagem_totvs(self, *, payload_hash: str, payload_raw: str) -> dict:
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO totvs_integration_messages (
                    payload_hash, status, payload_raw
                ) VALUES (%s, 'received', %s)
                ON CONFLICT (payload_hash) DO NOTHING
                RETURNING *
                """,
                (payload_hash, payload_raw),
            )
            row = cursor.fetchone()
            created = row is not None
            if row is None:
                cursor.execute(
                    "SELECT * FROM totvs_integration_messages WHERE payload_hash = %s",
                    (payload_hash,),
                )
                row = cursor.fetchone()
            result = dict(row)
            result["created"] = created
            return result

    def listar_codigos_recursos_totvs(self) -> tuple[str, ...]:
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT codigo
                FROM catalogo_recursos_pcfactory
                WHERE habilitado IS TRUE AND NULLIF(BTRIM(codigo), '') IS NOT NULL
                ORDER BY codigo
                """
            )
            return tuple(str(row["codigo"]).strip() for row in cursor.fetchall())

    def listar_setores_recursos_totvs(self) -> tuple[tuple[str, str], ...]:
        """Expõe o pertencimento canônico já cadastrado, sem inferir pelo nome."""

        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT codigo, tipo_setor
                FROM catalogo_recursos_pcfactory
                WHERE habilitado IS TRUE
                  AND NULLIF(BTRIM(codigo), '') IS NOT NULL
                  AND NULLIF(BTRIM(tipo_setor), '') IS NOT NULL
                ORDER BY codigo
                """
            )
            return tuple(
                (str(row["codigo"]).strip(), str(row["tipo_setor"]).strip())
                for row in cursor.fetchall()
            )

    def marcar_mensagem_totvs_erro(
        self,
        message_id: int,
        *,
        error_code: str,
        error_message: str,
        message=None,
    ) -> None:
        metadata = getattr(message, "metadata", None)
        event = getattr(message, "event", None)
        external_id = getattr(message, "external_id", None) if message is not None else None
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE totvs_integration_messages
                SET transaction = COALESCE(%s, transaction),
                    entity = COALESCE(%s, entity),
                    event = COALESCE(%s, event),
                    external_id = COALESCE(%s, external_id),
                    company_id = COALESCE(%s, company_id),
                    branch_id = COALESCE(%s, branch_id),
                    source_application = COALESCE(%s, source_application),
                    generated_on = COALESCE(%s, generated_on),
                    processed_at = CURRENT_TIMESTAMP,
                    status = 'error',
                    result_action = 'error',
                    error_code = %s,
                    error_message = %s
                WHERE id = %s AND status = 'received'
                """,
                (
                    getattr(metadata, "transaction", None),
                    getattr(event, "entity", None),
                    getattr(event, "event", None),
                    external_id or None,
                    getattr(metadata, "company_id", None),
                    getattr(metadata, "branch_id", None),
                    getattr(metadata, "source_application", None),
                    getattr(metadata, "generated_on", None),
                    str(error_code or "processing_error")[:80],
                    str(error_message or "Falha de processamento.")[:500],
                    int(message_id),
                ),
            )

    def registrar_diagnostico_totvs(self, *, message_id: int, message) -> dict:
        """Fecha uma mensagem somente leitura na inbox, sem efeito de negócio.

        Nenhuma tabela de planejamento ou execução é tocada. `entity`, `event` e
        `external_id` permanecem nulos porque um diagnóstico não descreve
        evento de negócio nem identifica OP.
        """

        metadata = getattr(message, "metadata", None)
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE totvs_integration_messages
                SET transaction = COALESCE(%s, transaction),
                    company_id = COALESCE(%s, company_id),
                    branch_id = COALESCE(%s, branch_id),
                    source_application = COALESCE(%s, source_application),
                    generated_on = COALESCE(%s, generated_on),
                    processed_at = CURRENT_TIMESTAMP,
                    status = 'ignored',
                    result_action = 'diagnostic',
                    activities_parsed = 0,
                    activities_projected = 0,
                    error_code = NULL,
                    error_message = NULL
                WHERE id = %s AND status = 'received'
                RETURNING *
                """,
                (
                    getattr(metadata, "transaction", None),
                    getattr(metadata, "company_id", None),
                    getattr(metadata, "branch_id", None),
                    getattr(metadata, "source_application", None),
                    getattr(metadata, "generated_on", None),
                    int(message_id),
                ),
            )
            row = cursor.fetchone()
            if row is None:
                cursor.execute(
                    "SELECT * FROM totvs_integration_messages WHERE id = %s",
                    (int(message_id),),
                )
                row = cursor.fetchone()
            if row is None:
                raise TotvsStoredMessageError("Mensagem TOTVS não encontrada na inbox.")
            return dict(row)

    def aplicar_production_order_totvs(
        self,
        *,
        message_id: int,
        payload_hash: str,
        message,
        mapping,
    ) -> dict:
        """Aplica inbox, cabeçalho e roteiro local à OP na mesma transação."""

        processed_at = _now()
        order = mapping.order
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT * FROM totvs_integration_messages WHERE id = %s FOR UPDATE",
                (int(message_id),),
            )
            inbox = cursor.fetchone()
            if inbox is None:
                raise TotvsIdentityConflictError("Mensagem TOTVS não encontrada na inbox.")
            if inbox["status"] in {"processed", "ignored"}:
                result = dict(inbox)
                result["already_final"] = True
                return result
            if inbox["status"] == "error":
                raise TotvsIdentityConflictError(
                    "Mensagem TOTVS já está marcada como erro e não será reaplicada."
                )

            cursor.execute(
                """
                UPDATE totvs_integration_messages
                SET transaction = %s,
                    entity = %s,
                    event = %s,
                    external_id = %s,
                    company_id = %s,
                    branch_id = %s,
                    source_application = %s,
                    generated_on = %s
                WHERE id = %s
                """,
                (
                    message.metadata.transaction,
                    message.event.entity,
                    message.event.event,
                    message.external_id,
                    message.metadata.company_id,
                    message.metadata.branch_id,
                    message.metadata.source_application,
                    message.metadata.generated_on,
                    int(message_id),
                ),
            )
            cursor.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                (order.totvs_unique_id,),
            )
            cursor.execute(
                """
                SELECT *
                FROM catalogo_pcp_ops
                WHERE totvs_unique_id = %s OR codigo_op = %s
                FOR UPDATE
                """,
                (order.totvs_unique_id, order.codigo_op),
            )
            matches = cursor.fetchall()
            if len(matches) > 1:
                raise TotvsIdentityConflictError(
                    "ProductionOrderUniqueID e Number apontam para OPs locais diferentes."
                )
            existing = matches[0] if matches else None
            if existing is not None:
                existing_unique = str(existing.get("totvs_unique_id") or "").strip()
                if existing_unique and existing_unique != order.totvs_unique_id:
                    raise TotvsIdentityConflictError(
                        "Number já está associado a outro ProductionOrderUniqueID."
                    )
                if existing_unique and str(existing["codigo_op"]) != order.codigo_op:
                    raise TotvsIdentityConflictError(
                        "ProductionOrderUniqueID já está associado a outro Number."
                    )
                temporal_result = self._check_totvs_temporal_order(
                    existing,
                    incoming_generated_on=order.totvs_generated_on,
                    incoming_payload_hash=payload_hash,
                )
                if temporal_result == "stale":
                    warnings = tuple(mapping.warnings) + (
                        "mensagem stale: planejamento mais recente foi preservado",
                    )
                    cursor.execute(
                        """
                        UPDATE totvs_integration_messages
                        SET status = 'ignored',
                            result_action = 'ignored_stale',
                            warnings = %s,
                            activities_parsed = %s,
                            activities_projected = 0,
                            processed_at = %s
                        WHERE id = %s
                        RETURNING *
                        """,
                        (
                            Jsonb(list(warnings)),
                            mapping.activities_parsed,
                            processed_at,
                            int(message_id),
                        ),
                    )
                    return dict(cursor.fetchone())

            action = "updated" if existing is not None else "inserted"
            if existing is None:
                self._insert_totvs_header_cursor(
                    cursor,
                    order=order,
                    payload_hash=payload_hash,
                    synchronized_at=processed_at,
                )
            else:
                self._update_totvs_header_cursor(
                    cursor,
                    order=order,
                    payload_hash=payload_hash,
                    synchronized_at=processed_at,
                )
            self._replace_totvs_operations_cursor(
                cursor,
                order=order,
                operations=mapping.operations,
                synchronized_at=processed_at,
            )
            cursor.execute(
                """
                UPDATE totvs_integration_messages
                SET status = 'processed',
                    result_action = %s,
                    warnings = %s,
                    activities_parsed = %s,
                    activities_projected = %s,
                    processed_at = %s,
                    error_code = NULL,
                    error_message = NULL
                WHERE id = %s
                RETURNING *
                """,
                (
                    action,
                    Jsonb(list(mapping.warnings)),
                    mapping.activities_parsed,
                    # Conta apenas as operações que viraram etapa executável do
                    # roteiro. O marco terminal é metadado para o outbound e
                    # continua fora dessa contagem, como no diagnóstico original.
                    sum(
                        1
                        for item in mapping.operations
                        if not (item.marco_terminal or item.inspecao_qualidade)
                    ),
                    processed_at,
                    int(message_id),
                ),
            )
            return dict(cursor.fetchone())

    @staticmethod
    def _check_totvs_temporal_order(
        existing,
        *,
        incoming_generated_on,
        incoming_payload_hash: str,
    ) -> str:
        current_generated_on = existing.get("totvs_generated_on")
        current_payload_hash = str(existing.get("totvs_payload_hash") or "").strip()
        # Uma linha legada ainda sem versão corporativa pode ser adotada pela
        # primeira mensagem oficial de mesmo Number.
        if not current_payload_hash and current_generated_on is None:
            return "apply"
        if incoming_generated_on is None or current_generated_on is None:
            raise TotvsTemporalConflictError(
                "GeneratedOn ausente impede ordenar duas versões da mesma OP."
            )
        if incoming_generated_on < current_generated_on:
            return "stale"
        if incoming_generated_on == current_generated_on:
            if current_payload_hash == incoming_payload_hash:
                return "same"
            raise TotvsTemporalConflictError(
                "Mesmo GeneratedOn recebido com payload diferente para a mesma OP."
            )
        return "apply"

    @staticmethod
    def _insert_totvs_header_cursor(
        cursor,
        *,
        order,
        payload_hash: str,
        synchronized_at: datetime,
    ) -> None:
        cursor.execute(
            """
            INSERT INTO catalogo_pcp_ops (
                codigo_op, produto_codigo, produto_descricao, quantidade,
                unidade, data_emissao, status_pcp, filial, local_estoque,
                roteiro, recurso, ativo, sincronizado_em,
                data_liberacao, inicio_planejado, fim_planejado, prioridade,
                totvs_unique_id, totvs_company_id, totvs_branch_id,
                totvs_generated_on, totvs_source_application, totvs_payload_hash
            ) VALUES (
                %s, %s, %s, %s,
                %s, NULL, %s, %s, %s,
                %s, NULL, TRUE, %s,
                %s, %s, %s, %s,
                %s, %s, %s,
                %s, %s, %s
            )
            """,
            (
                order.codigo_op,
                order.produto_codigo,
                order.produto_descricao,
                order.quantidade,
                order.unidade,
                order.status_pcp,
                order.filial,
                order.local_estoque,
                order.roteiro,
                synchronized_at,
                order.data_liberacao,
                order.inicio_planejado,
                order.fim_planejado,
                order.prioridade,
                order.totvs_unique_id,
                order.totvs_company_id,
                order.totvs_branch_id,
                order.totvs_generated_on,
                order.totvs_source_application,
                payload_hash,
            ),
        )

    @staticmethod
    def _update_totvs_header_cursor(
        cursor,
        *,
        order,
        payload_hash: str,
        synchronized_at: datetime,
    ) -> None:
        cursor.execute(
            """
            UPDATE catalogo_pcp_ops
            SET produto_codigo = %s,
                produto_descricao = %s,
                quantidade = %s,
                unidade = COALESCE(%s, unidade),
                status_pcp = COALESCE(%s, status_pcp),
                filial = COALESCE(%s, filial),
                local_estoque = COALESCE(%s, local_estoque),
                roteiro = COALESCE(%s, roteiro),
                ativo = TRUE,
                sincronizado_em = %s,
                data_liberacao = COALESCE(%s, data_liberacao),
                inicio_planejado = COALESCE(%s, inicio_planejado),
                fim_planejado = COALESCE(%s, fim_planejado),
                prioridade = COALESCE(%s, prioridade),
                totvs_unique_id = %s,
                totvs_company_id = %s,
                totvs_branch_id = %s,
                totvs_generated_on = %s,
                totvs_source_application = %s,
                totvs_payload_hash = %s
            WHERE codigo_op = %s
            """,
            (
                order.produto_codigo,
                order.produto_descricao,
                order.quantidade,
                order.unidade,
                order.status_pcp,
                order.filial,
                order.local_estoque,
                order.roteiro,
                synchronized_at,
                order.data_liberacao,
                order.inicio_planejado,
                order.fim_planejado,
                order.prioridade,
                order.totvs_unique_id,
                order.totvs_company_id,
                order.totvs_branch_id,
                order.totvs_generated_on,
                order.totvs_source_application,
                payload_hash,
                order.codigo_op,
            ),
        )

    @staticmethod
    def _replace_totvs_operations_cursor(
        cursor,
        *,
        order,
        operations,
        synchronized_at: datetime,
    ) -> None:
        # A atualização é estritamente local à OP. Linhas antigas permanecem
        # para rastreabilidade/FKs e apenas deixam de integrar o roteiro ativo.
        cursor.execute(
            """
            UPDATE catalogo_operacoes_op
            SET ativo = FALSE, sincronizado_em = %s
            WHERE codigo_op = %s AND ativo IS TRUE
            """,
            (synchronized_at, order.codigo_op),
        )
        for operation in operations:
            cursor.execute(
                """
                INSERT INTO catalogo_operacoes_op (
                    codigo_op, produto_codigo, produto_descricao,
                    numero_operacao, codigo_recurso, descricao_operacao,
                    tipo_setor, filial, tipo, roteiro, tempo_medio_segundos,
                    ordem, fonte, ativo, marco_terminal, inspecao_qualidade,
                    sincronizado_em,
                    totvs_activity_id, totvs_work_center_code, totvs_machine_code
                ) VALUES (
                    %s, %s, %s,
                    %s, %s, %s,
                    %s, %s, %s, %s, NULL,
                    %s, 'totvs_production_order_v1', %s, %s, %s,
                    %s,
                    %s, %s, %s
                )
                ON CONFLICT (codigo_op, totvs_activity_id)
                    WHERE totvs_activity_id IS NOT NULL
                DO UPDATE SET
                    produto_codigo = EXCLUDED.produto_codigo,
                    produto_descricao = EXCLUDED.produto_descricao,
                    numero_operacao = EXCLUDED.numero_operacao,
                    codigo_recurso = EXCLUDED.codigo_recurso,
                    descricao_operacao = EXCLUDED.descricao_operacao,
                    tipo_setor = EXCLUDED.tipo_setor,
                    filial = EXCLUDED.filial,
                    tipo = EXCLUDED.tipo,
                    roteiro = EXCLUDED.roteiro,
                    ordem = EXCLUDED.ordem,
                    fonte = EXCLUDED.fonte,
                    -- Marco terminal e inspeção da Qualidade continuam
                    -- inativos: são metadados do roteiro para o outbound e para
                    -- a aba Qualidade, nunca operação do posto do operador.
                    ativo = EXCLUDED.ativo,
                    marco_terminal = EXCLUDED.marco_terminal,
                    inspecao_qualidade = EXCLUDED.inspecao_qualidade,
                    sincronizado_em = EXCLUDED.sincronizado_em,
                    totvs_work_center_code = EXCLUDED.totvs_work_center_code,
                    totvs_machine_code = EXCLUDED.totvs_machine_code
                """,
                (
                    operation.codigo_op,
                    operation.produto_codigo,
                    operation.produto_descricao,
                    operation.numero_operacao,
                    operation.codigo_recurso,
                    operation.descricao_operacao,
                    operation.tipo_setor,
                    operation.filial,
                    operation.tipo,
                    operation.roteiro,
                    operation.ordem,
                    not (operation.marco_terminal or operation.inspecao_qualidade),
                    operation.marco_terminal,
                    operation.inspecao_qualidade,
                    synchronized_at,
                    operation.totvs_activity_id,
                    operation.totvs_work_center_code,
                    operation.totvs_machine_code,
                ),
            )
