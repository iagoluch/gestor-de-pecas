"""Observabilidade PostgreSQL da simulação (seção 22).

Conexão própria, **somente leitura**, separada do pool da API para que a
observação não dispute o recurso que está sendo medido. Nenhuma manutenção
pesada roda durante o teste: sem VACUUM, sem ANALYZE, sem REINDEX.

O que o coletor produz é série temporal. Quem decide se um número virou defeito
é o detector (``simulacao/detector.py``), com os limiares configuráveis da
seção 36.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import psycopg
from psycopg.rows import dict_row


#: Tabelas cujo crescimento conta a história da execução.
TABELAS_RELEVANTES = (
    "apontamentos_operacionais",
    "apontamentos_corte",
    "eventos_apontamento_operador",
    "eventos_estado_recurso",
    "eventos_quantidade_producao",
    "eventos_destaque_tarefa",
    "participacoes_operador",
    "operadores_evento_apontamento",
    "qualidade_primeira_peca",
    "qualidade_primeira_peca_autorizacoes",
    "alertas_internos",
    "sessoes_recurso",
    "totvs_outbox",
    "totvs_integration_messages",
    "catalogo_pcp_ops",
    "catalogo_operacoes_op",
    "historico",
)


@dataclass
class DatabaseObserver:
    dsn: str
    database: str
    _baseline: dict = field(default_factory=dict)
    _anterior: dict | None = None

    # ------------------------------------------------------------------
    def _connect(self):
        return psycopg.connect(
            self.dsn,
            row_factory=dict_row,
            connect_timeout=8,
            autocommit=True,
            application_name="gestor_simulacao_observador",
        )

    def _one(self, cursor, sql: str, args: tuple = ()) -> dict:
        cursor.execute(sql, args)
        row = cursor.fetchone()
        return dict(row) if row else {}

    # ------------------------------------------------------------------
    def coletar(self) -> dict:
        with self._connect() as conn, conn.cursor() as cur:
            atividade = self._one(
                cur,
                """
                SELECT
                    COUNT(*)                                             AS conexoes,
                    COUNT(*) FILTER (WHERE state = 'active')             AS ativas,
                    COUNT(*) FILTER (WHERE state = 'idle')               AS idle,
                    COUNT(*) FILTER (WHERE state = 'idle in transaction') AS idle_in_transaction,
                    COUNT(*) FILTER (WHERE wait_event_type = 'Lock')     AS esperando_lock,
                    COALESCE(MAX(EXTRACT(EPOCH FROM (now() - query_start)))
                             FILTER (WHERE state = 'active'), 0)         AS query_ativa_mais_longa_s,
                    COALESCE(MAX(EXTRACT(EPOCH FROM (now() - xact_start))), 0) AS transacao_mais_longa_s
                FROM pg_stat_activity
                WHERE datname = %s
                """,
                (self.database,),
            )
            estatisticas = self._one(
                cur,
                """
                SELECT xact_commit, xact_rollback, deadlocks, conflicts, temp_files,
                       temp_bytes, blks_read, blks_hit, tup_returned, tup_fetched,
                       tup_inserted, tup_updated, tup_deleted,
                       pg_database_size(datname) AS tamanho_bytes
                FROM pg_stat_database WHERE datname = %s
                """,
                (self.database,),
            )
            locks = self._one(
                cur,
                """
                SELECT COUNT(*) AS total,
                       COUNT(*) FILTER (WHERE NOT granted) AS nao_concedidos
                FROM pg_locks
                """,
            )
            cur.execute(
                """
                SELECT pid, state, wait_event_type, wait_event,
                       EXTRACT(EPOCH FROM (now() - query_start)) AS duracao_s,
                       LEFT(REGEXP_REPLACE(query, '\\s+', ' ', 'g'), 200) AS query
                FROM pg_stat_activity
                WHERE datname = %s AND state = 'active'
                  AND query_start IS NOT NULL
                  AND now() - query_start > interval '1 second'
                  AND pid <> pg_backend_pid()
                ORDER BY duracao_s DESC LIMIT 5
                """,
                (self.database,),
            )
            lentas = [dict(row) for row in cur.fetchall()]

            cur.execute(
                """
                SELECT blocked.pid AS bloqueado, blocking.pid AS bloqueador,
                       LEFT(REGEXP_REPLACE(blocked.query, '\\s+', ' ', 'g'), 160) AS query_bloqueada
                FROM pg_stat_activity blocked
                JOIN LATERAL unnest(pg_blocking_pids(blocked.pid)) AS blocking(pid) ON TRUE
                WHERE blocked.datname = %s
                LIMIT 5
                """,
                (self.database,),
            )
            bloqueios = [dict(row) for row in cur.fetchall()]

            contagens: dict[str, int] = {}
            for tabela in TABELAS_RELEVANTES:
                try:
                    cur.execute(f'SELECT COUNT(*) AS n FROM "{tabela}"')
                    contagens[tabela] = int(cur.fetchone()["n"])
                except Exception:
                    contagens[tabela] = -1

            wal = {}
            try:
                wal = self._one(
                    cur,
                    "SELECT wal_records, wal_bytes, wal_write, wal_sync FROM pg_stat_wal",
                )
            except Exception:
                wal = {}

        blks_hit = float(estatisticas.get("blks_hit") or 0)
        blks_read = float(estatisticas.get("blks_read") or 0)
        cache_hit = (blks_hit / (blks_hit + blks_read)) if (blks_hit + blks_read) else None

        amostra = {
            "conexoes": atividade,
            "estatisticas": {
                key: (float(value) if isinstance(value, (int, float)) else value)
                for key, value in estatisticas.items()
            },
            "locks": locks,
            "queries_lentas": lentas,
            "bloqueios": bloqueios,
            "tabelas": contagens,
            "wal": wal,
            "cache_hit_ratio": round(cache_hit, 4) if cache_hit is not None else None,
        }
        amostra["deltas"] = self._deltas(amostra)
        self._anterior = amostra
        if not self._baseline:
            self._baseline = {
                "tabelas": dict(contagens),
                "estatisticas": dict(estatisticas),
                "coletado_em": datetime.now().isoformat(),
            }
        return amostra

    # ------------------------------------------------------------------
    def _deltas(self, atual: dict) -> dict:
        if not self._anterior:
            return {}
        anterior = self._anterior
        delta_tabelas = {
            nome: atual["tabelas"].get(nome, 0) - anterior["tabelas"].get(nome, 0)
            for nome in atual["tabelas"]
            if atual["tabelas"].get(nome, -1) >= 0 and anterior["tabelas"].get(nome, -1) >= 0
        }
        def diff(chave: str) -> float:
            return float(atual["estatisticas"].get(chave) or 0) - float(
                anterior["estatisticas"].get(chave) or 0
            )
        return {
            "tabelas": {nome: valor for nome, valor in delta_tabelas.items() if valor},
            "xact_commit": diff("xact_commit"),
            "xact_rollback": diff("xact_rollback"),
            "deadlocks": diff("deadlocks"),
            "tamanho_bytes": diff("tamanho_bytes"),
        }

    @property
    def baseline(self) -> dict:
        return dict(self._baseline)

    def crescimento_total(self) -> dict[str, int]:
        if not self._baseline or not self._anterior:
            return {}
        base = self._baseline["tabelas"]
        atual = self._anterior["tabelas"]
        return {
            nome: atual.get(nome, 0) - base.get(nome, 0)
            for nome in base
            if atual.get(nome, -1) >= 0 and base.get(nome, -1) >= 0
        }

    # ------------------------------------------------------------------
    def consultar(self, sql: str, args: tuple = ()) -> list[dict]:
        """Consulta de diagnóstico/validação (seção 9: SQL só para observar)."""

        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(sql, args)
            return [dict(row) for row in cur.fetchall()]

    def escalar(self, sql: str, args: tuple = ()) -> Any:
        linhas = self.consultar(sql, args)
        if not linhas:
            return None
        return next(iter(linhas[0].values()))
