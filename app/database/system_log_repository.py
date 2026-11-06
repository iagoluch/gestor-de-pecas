"""Persistência do log do sistema (migration 74).

Quem grava é o ``SystemLog`` de ``backend/observability/system_log.py``, em lote
e fora da requisição. Aqui só há SQL: gravar lote, listar com filtros, resumo
por área e limpeza por retenção.
"""

from __future__ import annotations

import json

from psycopg.types.json import Jsonb

LIMITE_PADRAO = 200
LIMITE_MAXIMO = 1000
NIVEIS = ("info", "aviso", "erro")


def _json_seguro(valor):
    return json.loads(json.dumps(valor, ensure_ascii=False, default=str))


class SystemLogRepositoryMixin:
    def gravar_log_lote(self, entradas):
        """Insere as entradas de uma vez. Devolve quantas gravou."""

        entradas = list(entradas)
        if not entradas:
            return 0
        linhas = [
            (
                e["quando"], e["area"], e["nivel"], e["evento"], e["mensagem"],
                e.get("usuario"), e.get("request_id"), e.get("metodo"), e.get("rota"),
                e.get("status_http"), e.get("duracao_ms"),
                None if not e.get("detalhe") else Jsonb(_json_seguro(e["detalhe"])),
            )
            for e in entradas
        ]
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.executemany(
                """
                INSERT INTO log_sistema
                    (quando, area, nivel, evento, mensagem, usuario, request_id,
                     metodo, rota, status_http, duracao_ms, detalhe)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                linhas,
            )
        return len(linhas)

    def listar_log(self, *, area=None, nivel=None, busca=None, usuario=None,
                   desde=None, ate=None, limite=LIMITE_PADRAO):
        """Mais recente primeiro. ``ate`` é exclusivo (use o dia seguinte)."""

        where, params = [], []
        if area:
            where.append("area = %s")
            params.append(area)
        if nivel:
            where.append("nivel = %s")
            params.append(nivel)
        if usuario:
            where.append("usuario ILIKE %s")
            params.append(f"%{usuario}%")
        if busca:
            where.append("(mensagem ILIKE %s OR rota ILIKE %s OR evento ILIKE %s)")
            params.extend([f"%{busca}%"] * 3)
        if desde is not None:
            where.append("quando >= %s")
            params.append(desde)
        if ate is not None:
            where.append("quando < %s")
            params.append(ate)
        limite = max(1, min(int(limite or LIMITE_PADRAO), LIMITE_MAXIMO))
        sql = (
            "SELECT id, quando, area, nivel, evento, mensagem, usuario, request_id, metodo,"  # nosec B608 -- só fragmentos fixos do módulo; todo valor do usuário vai por %s
            " rota, status_http, duracao_ms::float AS duracao_ms, detalhe FROM log_sistema"
            + (" WHERE " + " AND ".join(where) if where else "")
            + " ORDER BY quando DESC, id DESC LIMIT %s"
        )
        params.append(limite)
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(sql, params)
            return [dict(row) for row in cursor.fetchall()]

    def resumo_log(self, *, desde):
        """Contagem por área e nível desde ``desde``."""

        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT area, nivel, COUNT(*) AS total FROM log_sistema"
                " WHERE quando >= %s GROUP BY area, nivel",
                (desde,),
            )
            return [dict(row) for row in cursor.fetchall()]

    def limpar_log(self, *, antes_de):
        """Apaga o que é anterior a ``antes_de``. Devolve quantos apagou."""

        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute("DELETE FROM log_sistema WHERE quando < %s", (antes_de,))
            return cursor.rowcount


__all__ = ["NIVEIS", "SystemLogRepositoryMixin"]
