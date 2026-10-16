"""Persistência do custo por hora (R$/h) de recurso e operador (migration 63).

Só guarda e lista o valor; o cálculo de custo (horas x taxa) vive na camada de
serviço. Recurso é identificado pelo nome sem caixa (``UPPER``): ``laser1`` e
``LASER1`` são a mesma linha.
"""

from __future__ import annotations

from decimal import Decimal


def _chave_recurso(recurso):
    return str(recurso or "").strip().upper()


class CostRateRepositoryMixin:
    def listar_custos_hora_recurso(self):
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT recurso, valor_hora, atualizado_em, atualizado_por
                FROM custo_hora_recurso
                ORDER BY recurso_chave
                """
            )
            return [dict(row) for row in cursor.fetchall()]

    def salvar_custo_hora_recurso(self, recurso: str, valor_hora: Decimal, usuario: str) -> None:
        """Grava (ou troca) o R$/h do recurso. Valor <= 0 é recusado pelo banco."""

        chave = _chave_recurso(recurso)
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO custo_hora_recurso (
                    recurso_chave, recurso, valor_hora, atualizado_em, atualizado_por
                ) VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (recurso_chave) DO UPDATE SET
                    recurso = EXCLUDED.recurso,
                    valor_hora = EXCLUDED.valor_hora,
                    atualizado_em = EXCLUDED.atualizado_em,
                    atualizado_por = EXCLUDED.atualizado_por
                """,
                (chave, str(recurso).strip(), valor_hora, self._now(), usuario),
            )

    def listar_custos_hora_operador(self):
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT operador_id, valor_hora, atualizado_em, atualizado_por
                FROM custo_hora_operador
                ORDER BY operador_id
                """
            )
            return [dict(row) for row in cursor.fetchall()]

    def salvar_custo_hora_operador(self, operador_id: int, valor_hora: Decimal, usuario: str) -> None:
        """Grava (ou troca) o R$/h do operador. Operador inexistente viola a FK."""

        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO custo_hora_operador (
                    operador_id, valor_hora, atualizado_em, atualizado_por
                ) VALUES (%s, %s, %s, %s)
                ON CONFLICT (operador_id) DO UPDATE SET
                    valor_hora = EXCLUDED.valor_hora,
                    atualizado_em = EXCLUDED.atualizado_em,
                    atualizado_por = EXCLUDED.atualizado_por
                """,
                (int(operador_id), valor_hora, self._now(), usuario),
            )
