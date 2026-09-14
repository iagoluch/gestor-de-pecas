"""Persistência da sincronização de OP sob demanda (Etapa 6.1).

Aqui não existe regra de integração: nenhum SOAP, nenhum HTTP, nenhuma decisão
de reenvio. O papel deste mixin é apenas (a) responder se a OP já existe
localmente e (b) arbitrar, no PostgreSQL, quem é o líder de uma solicitação.

A arbitragem é feita pelo banco de propósito. Dois operadores em processos
diferentes — ou duas réplicas do backend — digitando a mesma OP ausente
precisam convergir para UMA sincronização lógica, e isso não pode depender do
frontend nem de um lock em memória.
"""

from __future__ import annotations

from datetime import datetime, timedelta


MAX_ERROR_MESSAGE_CHARS = 2000

SYNC_REQUEST_COLUMNS = """
    id, codigo_op, status, attempts, requested_at, finished_at,
    updated_at, error_code, error_message
"""


def _truncate(value, limit: int = MAX_ERROR_MESSAGE_CHARS) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    return text if len(text) <= limit else text[: limit - 3] + "..."


class TotvsOpSyncRepositoryMixin:
    def buscar_cabecalho_op_local_totvs(self, codigo_op: str) -> dict | None:
        """Retorna o cabeçalho e a contagem de operações ativas, mesmo se zero."""
        codigo = str(codigo_op or "").strip().upper()
        if not codigo:
            return None
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT pcp.codigo_op,
                       pcp.produto_codigo,
                       pcp.produto_descricao,
                       pcp.quantidade,
                       pcp.unidade,
                       pcp.filial,
                       pcp.totvs_unique_id,
                       pcp.totvs_company_id,
                       pcp.totvs_branch_id,
                       pcp.sincronizado_em,
                       COUNT(operacao.id) FILTER (WHERE operacao.ativo) AS operacoes_ativas
                  FROM catalogo_pcp_ops pcp
                  LEFT JOIN catalogo_operacoes_op operacao
                    ON operacao.codigo_op = pcp.codigo_op
                 WHERE pcp.codigo_op = %s
                   AND pcp.ativo = TRUE
                 GROUP BY pcp.codigo_op, pcp.produto_codigo, pcp.produto_descricao,
                          pcp.quantidade, pcp.unidade, pcp.filial, pcp.totvs_unique_id,
                          pcp.totvs_company_id, pcp.totvs_branch_id, pcp.sincronizado_em
                """,
                (codigo,),
            )
            row = cursor.fetchone()
        return dict(row) if row is not None else None

    def buscar_op_local_totvs(self, codigo_op: str) -> dict | None:
        """Existe OP canônica ativa com roteiro operacional utilizável?

        Cabeçalho sem operação ativa é preservado, mas não é carregável para o
        operador. ``buscar_cabecalho_op_local_totvs`` permite distingui-lo de
        uma OP realmente ausente sem inventar roteiro.
        """

        row = self.buscar_cabecalho_op_local_totvs(codigo_op)
        if row is None:
            return None
        if int(row.get("operacoes_ativas") or 0) <= 0:
            return None
        return row

    def abrir_solicitacao_sync_op(
        self,
        *,
        codigo_op: str,
        agora: datetime,
        negative_ttl_seconds: int,
        stale_after_seconds: int,
    ) -> dict:
        """Decide o papel do chamador: líder, seguidor ou cache negativo.

        ``stale_after_seconds`` recupera uma solicitação órfã: se o processo que
        liderava morreu, a OP não pode ficar bloqueada para sempre. Passado o
        prazo, o próximo pedido reassume a liderança.
        """

        codigo = str(codigo_op or "").strip().upper()
        if not codigo:
            raise ValueError("codigo_op é obrigatório para solicitar sincronização.")
        stale_before = agora - timedelta(seconds=max(int(stale_after_seconds), 1))
        negative_floor = agora - timedelta(seconds=max(int(negative_ttl_seconds), 0))
        with self.connection() as connection, connection.cursor() as cursor:
            # 1. Tenta nascer líder. Só um INSERT sobrevive à UNIQUE.
            cursor.execute(
                f"""
                INSERT INTO totvs_op_sync_requests (
                    codigo_op, status, attempts, requested_at, updated_at
                ) VALUES (%s, 'PENDING', 1, %s, %s)
                ON CONFLICT (codigo_op) DO NOTHING
                RETURNING {SYNC_REQUEST_COLUMNS}
                """,
                (codigo, agora, agora),
            )
            row = cursor.fetchone()
            if row is not None:
                return {"role": "leader", **dict(row)}

            cursor.execute(
                f"""
                SELECT {SYNC_REQUEST_COLUMNS}
                  FROM totvs_op_sync_requests
                 WHERE codigo_op = %s
                 FOR UPDATE
                """,
                (codigo,),
            )
            current = cursor.fetchone()
            if current is None:  # pragma: no cover - corrida improvável
                return {"role": "follower", "id": None, "status": "PENDING"}
            current = dict(current)

            # 2. Alguém está sincronizando agora: seguir, não abrir outra.
            if current["status"] == "PENDING" and current["updated_at"] > stale_before:
                return {"role": "follower", **current}

            # 3. Negativa recente: não martelar o ERP. TTL curto, não definitivo.
            if (
                current["status"] == "NOT_FOUND"
                and current["finished_at"] is not None
                and negative_ttl_seconds > 0
                and current["finished_at"] > negative_floor
            ):
                return {"role": "negative_cache", **current}

            # 4. Reabre a MESMA linha: histórico não se acumula por OP.
            cursor.execute(
                f"""
                UPDATE totvs_op_sync_requests
                   SET status = 'PENDING',
                       attempts = attempts + 1,
                       requested_at = %s,
                       finished_at = NULL,
                       updated_at = %s,
                       error_code = NULL,
                       error_message = NULL
                 WHERE id = %s
                RETURNING {SYNC_REQUEST_COLUMNS}
                """,
                (agora, agora, current["id"]),
            )
            return {"role": "leader", **dict(cursor.fetchone())}

    def finalizar_solicitacao_sync_op(
        self,
        *,
        solicitacao_id: int,
        status: str,
        agora: datetime,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> None:
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE totvs_op_sync_requests
                   SET status = %s,
                       finished_at = %s,
                       updated_at = %s,
                       error_code = %s,
                       error_message = %s
                 WHERE id = %s
                """,
                (
                    str(status).strip().upper(),
                    agora,
                    agora,
                    _truncate(error_code, 120),
                    _truncate(error_message),
                    int(solicitacao_id),
                ),
            )

    def consultar_solicitacao_sync_op(self, codigo_op: str) -> dict | None:
        codigo = str(codigo_op or "").strip().upper()
        if not codigo:
            return None
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT {SYNC_REQUEST_COLUMNS}
                  FROM totvs_op_sync_requests
                 WHERE codigo_op = %s
                """,
                (codigo,),
            )
            row = cursor.fetchone()
        return dict(row) if row is not None else None


__all__ = ["TotvsOpSyncRepositoryMixin"]
