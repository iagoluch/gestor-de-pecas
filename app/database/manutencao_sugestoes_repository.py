"""Persistência das sugestões de manutenção (migration 68).

Uma sugestão nasce de uma parada NÃO planejada do grupo de manutenção corretiva
(``mes/services/maintenance_suggestions.py``) e só tem dois destinos: ``aceita``
ou ``descartada``. "Aceita" é um carimbo interno: nada aqui fala com o TOTVS nem
com o outbox. Uma sugestão decidida nunca volta a ``sugerida`` (o UPDATE exige
``status = 'sugerida'`` e o gatilho do banco recusa o contrário).
"""

from __future__ import annotations

_COLUNAS = (
    "id, recurso, setor, parada_inicio, parada_fim, parada_segundos, motivo, op, status,"
    " criada_em, decidido_por_id, decidido_por_nome, decidido_em, nota"
)


class ManutencaoSugestoesRepositoryMixin:
    def gravar_sugestoes_manutencao(self, paradas):
        """Insere as paradas que ainda não têm sugestão; idempotente.

        A chave é ``(recurso, parada_inicio)``. Se a sugestão já existe e AINDA está
        ``sugerida``, só a duração/fim é atualizada (parada que seguia em curso na
        geração anterior). Decidida (aceita/descartada) nunca é tocada.
        """

        paradas = list(paradas or [])
        if not paradas:
            return 0
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.executemany(
                """
                INSERT INTO manutencao_sugestoes
                    (recurso, setor, parada_inicio, parada_fim, parada_segundos, motivo, op, criada_em)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (recurso, parada_inicio) DO UPDATE
                SET parada_fim = EXCLUDED.parada_fim,
                    parada_segundos = EXCLUDED.parada_segundos
                WHERE manutencao_sugestoes.status = 'sugerida'
                  AND (manutencao_sugestoes.parada_fim, manutencao_sugestoes.parada_segundos)
                      IS DISTINCT FROM (EXCLUDED.parada_fim, EXCLUDED.parada_segundos)
                """,
                [
                    (
                        parada["recurso"],
                        parada.get("setor"),
                        parada["parada_inicio"],
                        parada.get("parada_fim"),
                        int(parada["parada_segundos"]),
                        parada["motivo"],
                        parada.get("op"),
                        self._now(),
                    )
                    for parada in paradas
                ],
            )
        return len(paradas)

    def listar_sugestoes_manutencao(self, status, limite=200):
        """Mais recentes primeiro (início da parada)."""

        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT {_COLUNAS}
                FROM manutencao_sugestoes
                WHERE status = %s
                ORDER BY parada_inicio DESC, id DESC
                LIMIT %s
                """,  # nosec B608 -- _COLUNAS é constante local, nunca entrada externa
                (status, int(limite)),
            )
            return [dict(row) for row in cursor.fetchall()]

    def buscar_sugestao_manutencao(self, sugestao_id):
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                f"SELECT {_COLUNAS} FROM manutencao_sugestoes WHERE id = %s",  # nosec B608 -- constante local
                (int(sugestao_id),),
            )
            row = cursor.fetchone()
            return dict(row) if row else None

    def decidir_sugestao_manutencao(
        self, sugestao_id, *, status, usuario_id, usuario_nome, nota=None, quando=None
    ):
        """Decide uma sugestão ainda ``sugerida``; ``None`` se não existe ou já foi decidida.

        Um único UPDATE condicional (``WHERE status = 'sugerida' ... RETURNING``):
        duas decisões simultâneas nunca passam as duas.
        """

        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                f"""
                UPDATE manutencao_sugestoes
                SET status = %s, decidido_por_id = %s, decidido_por_nome = %s,
                    decidido_em = %s, nota = %s
                WHERE id = %s AND status = 'sugerida'
                RETURNING {_COLUNAS}
                """,  # nosec B608 -- _COLUNAS é constante local, nunca entrada externa
                (
                    status,
                    int(usuario_id),
                    usuario_nome,
                    quando or self._now(),
                    nota,
                    int(sugestao_id),
                ),
            )
            row = cursor.fetchone()
            return dict(row) if row else None


__all__ = ["ManutencaoSugestoesRepositoryMixin"]
