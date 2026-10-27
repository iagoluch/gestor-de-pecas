"""Persistência da decisão sobre uma RNC (migration 67). SOMENTE INSERÇÃO.

Não existe segundo domínio de RNC: esta tabela é filha de ``qualidade_rnc`` e só
guarda quem decidiu o quê e por quê. Este repositório propositalmente não tem
UPDATE nem DELETE, não cria evento de quantidade e não toca em
``qualidade_pecas_inspecionadas`` nem em ``qualidade_rnc`` (o trigger do banco
também recusa UPDATE). A decisão vigente é a de maior ``id``.
"""

from __future__ import annotations

_COLUNAS = "id, rnc_id, decisao, justificativa, decidido_por_id, decidido_por_nome, quando"
LIMITE_MAXIMO_LISTA_RNC = 200


class QualityRncDecisionRepositoryMixin:
    def buscar_rnc_com_resultado(self, rnc_id):
        """RNC + resultado registrado da peça (``APROVADA``/``RETRABALHO``/``REFUGO``).

        ``None`` quando a RNC não existe. ``resultado_peca`` é ``None`` se a peça
        ligada à RNC não existir mais.
        """

        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT rnc.id, rnc.codigo, rnc.codigo_op, rnc.produto_codigo,
                       rnc.numero_peca, rnc.motivo,
                       peca.resultado AS resultado_peca
                FROM qualidade_rnc rnc
                LEFT JOIN qualidade_pecas_inspecionadas peca ON peca.rnc_id = rnc.id
                WHERE rnc.id = %s
                """,
                (int(rnc_id),),
            )
            row = cursor.fetchone()
            return dict(row) if row else None

    def registrar_decisao_rnc(
        self, rnc_id, *, decisao, justificativa, usuario_id, usuario_nome, quando=None
    ):
        """Acrescenta uma linha de decisão (nunca altera as anteriores)."""

        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                f"""
                INSERT INTO qualidade_rnc_decisoes
                    (rnc_id, decisao, justificativa, decidido_por_id, decidido_por_nome, quando)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING {_COLUNAS}
                """,  # nosec B608 -- _COLUNAS é constante local, nunca entrada externa
                (
                    int(rnc_id),
                    decisao,
                    justificativa,
                    int(usuario_id),
                    usuario_nome,
                    quando or self._now(),
                ),
            )
            return dict(cursor.fetchone())

    def listar_decisoes_rnc(self, rnc_id):
        """Histórico da RNC, da decisão mais recente (vigente) para a mais antiga."""

        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT {_COLUNAS}
                FROM qualidade_rnc_decisoes
                WHERE rnc_id = %s
                ORDER BY id DESC
                """,  # nosec B608 -- _COLUNAS é constante local, nunca entrada externa
                (int(rnc_id),),
            )
            return [dict(row) for row in cursor.fetchall()]

    def listar_rncs_para_decisao(self, *, limite, somente_sem_decisao=False):
        """RNCs mais recentes primeiro, cada uma com o resultado da peça e a decisão vigente.

        Uma única consulta: a vigente (maior ``id``) vem por ``LATERAL ... LIMIT 1``.
        ``decisao_vigente`` é ``None`` quando a RNC ainda não tem decisão. Somente leitura.
        """

        limite = int(limite)
        if not 1 <= limite <= LIMITE_MAXIMO_LISTA_RNC:
            raise ValueError(f"limite deve estar entre 1 e {LIMITE_MAXIMO_LISTA_RNC}.")
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT rnc.id, rnc.codigo, rnc.motivo, rnc.numero_peca,
                       rnc.codigo_op AS op, rnc.produto_codigo AS produto,
                       rnc.codigo_recurso AS recurso, rnc.registrada_em AS criada_em,
                       peca.resultado AS resultado_peca,
                       dec.id AS dec_id, dec.decisao AS dec_decisao,
                       dec.justificativa AS dec_justificativa,
                       dec.decidido_por_nome AS dec_decidido_por_nome,
                       dec.quando AS dec_quando
                FROM qualidade_rnc rnc
                LEFT JOIN qualidade_pecas_inspecionadas peca ON peca.rnc_id = rnc.id
                LEFT JOIN LATERAL (
                    SELECT d.id, d.decisao, d.justificativa, d.decidido_por_nome, d.quando
                    FROM qualidade_rnc_decisoes d
                    WHERE d.rnc_id = rnc.id
                    ORDER BY d.id DESC
                    LIMIT 1
                ) dec ON TRUE
                WHERE (NOT %s OR dec.id IS NULL)
                ORDER BY rnc.registrada_em DESC, rnc.id DESC
                LIMIT %s
                """,
                (bool(somente_sem_decisao), limite),
            )
            itens = []
            for row in cursor.fetchall():
                item = dict(row)
                vigente_id = item.pop("dec_id")
                vigente = {
                    "decisao": item.pop("dec_decisao"),
                    "justificativa": item.pop("dec_justificativa"),
                    "decidido_por_nome": item.pop("dec_decidido_por_nome"),
                    "quando": item.pop("dec_quando"),
                }
                item["decisao_vigente"] = vigente if vigente_id is not None else None
                itens.append(item)
            return itens


__all__ = ["QualityRncDecisionRepositoryMixin"]
