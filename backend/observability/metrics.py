"""Métricas de tempo de execução: PostgreSQL e processo da API.

Todas as consultas são ``SELECT``/``SHOW`` sobre catálogos e visões de
estatística (``pg_stat_activity``, ``pg_stat_database``, ``pg_locks``). Nenhuma
manutenção pesada é disparada daqui: sem ``VACUUM``, sem ``ANALYZE``, sem
``REINDEX``. O coletor produz série temporal; quem interpreta é o
desenvolvedor.
"""

from __future__ import annotations

import logging
import os
from typing import Any


#: Tabelas cujo crescimento conta a história do turno.
TRACKED_TABLES = (
    "apontamentos_operacionais",
    "apontamentos_corte",
    "eventos_apontamento_operador",
    "eventos_estado_recurso",
    "eventos_quantidade_producao",
    "eventos_destaque_tarefa",
    "qualidade_primeira_peca",
    "alertas_internos",
    "totvs_outbox",
    "historico",
)


def _scalar_row(cursor, sql: str, args: tuple = ()) -> dict:
    cursor.execute(sql, args)
    row = cursor.fetchone()
    return dict(row) if row else {}


def _numeric(value: Any) -> Any:
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, (int, float)):
        return value
    try:
        return float(value)
    except (TypeError, ValueError):
        return value


def collect_postgres_metrics(database, *, include_table_counts: bool = True) -> dict:
    """Retrato do PostgreSQL visto pela conexão informada.

    ``database`` é qualquer facade com ``connection()`` e ``safe_target`` — o
    pool da própria API (TESTE) ou o pool somente leitura do REAL.
    """

    target = dict(getattr(database, "safe_target", {}) or {})
    dbname = str(target.get("dbname") or "")
    with database.connection() as connection, connection.cursor() as cursor:
        activity = _scalar_row(
            cursor,
            """
            SELECT
                COUNT(*)                                              AS conexoes,
                COUNT(*) FILTER (WHERE state = 'active')              AS ativas,
                COUNT(*) FILTER (WHERE state = 'idle')                AS idle,
                COUNT(*) FILTER (WHERE state = 'idle in transaction') AS idle_in_transaction,
                COUNT(*) FILTER (WHERE wait_event_type = 'Lock')      AS esperando_lock,
                COALESCE(MAX(EXTRACT(EPOCH FROM (now() - query_start)))
                         FILTER (WHERE state = 'active'), 0)          AS query_ativa_mais_longa_s,
                COALESCE(MAX(EXTRACT(EPOCH FROM (now() - xact_start))), 0)
                                                                      AS transacao_mais_longa_s
            FROM pg_stat_activity
            WHERE datname = %s
            """,
            (dbname,),
        )
        statistics = _scalar_row(
            cursor,
            """
            SELECT numbackends, xact_commit, xact_rollback, deadlocks, conflicts,
                   temp_files, temp_bytes, blks_read, blks_hit,
                   tup_returned, tup_fetched, tup_inserted, tup_updated, tup_deleted,
                   pg_database_size(datname) AS tamanho_bytes
            FROM pg_stat_database WHERE datname = %s
            """,
            (dbname,),
        )
        locks = _scalar_row(
            cursor,
            """
            SELECT COUNT(*) AS total,
                   COUNT(*) FILTER (WHERE NOT granted) AS nao_concedidos
            FROM pg_locks
            """,
        )
        cursor.execute(
            """
            SELECT pid, state, wait_event_type, wait_event, application_name,
                   EXTRACT(EPOCH FROM (now() - query_start)) AS duracao_s,
                   LEFT(REGEXP_REPLACE(query, '\\s+', ' ', 'g'), 240) AS query
            FROM pg_stat_activity
            WHERE datname = %s AND state = 'active'
              AND query_start IS NOT NULL
              AND now() - query_start > interval '1 second'
              AND pid <> pg_backend_pid()
            ORDER BY duracao_s DESC LIMIT 8
            """,
            (dbname,),
        )
        slow_queries = [dict(row) for row in cursor.fetchall()]
        cursor.execute(
            """
            SELECT blocked.pid AS bloqueado, blocking.pid AS bloqueador,
                   blocked.wait_event_type, blocked.wait_event,
                   LEFT(REGEXP_REPLACE(blocked.query, '\\s+', ' ', 'g'), 200) AS query_bloqueada
            FROM pg_stat_activity blocked
            JOIN LATERAL unnest(pg_blocking_pids(blocked.pid)) AS blocking(pid) ON TRUE
            WHERE blocked.datname = %s
            LIMIT 8
            """,
            (dbname,),
        )
        blocked = [dict(row) for row in cursor.fetchall()]

        table_counts: dict[str, int] = {}
        if include_table_counts:
            for table in TRACKED_TABLES:
                try:
                    cursor.execute(f'SELECT COUNT(*) AS n FROM "{table}"')
                    table_counts[table] = int(cursor.fetchone()["n"])
                except Exception:
                    connection.rollback()
                    table_counts[table] = -1

    blks_hit = float(statistics.get("blks_hit") or 0)
    blks_read = float(statistics.get("blks_read") or 0)
    cache_hit = (blks_hit / (blks_hit + blks_read)) if (blks_hit + blks_read) else None

    return {
        "target": target,
        "connections": {key: _numeric(value) for key, value in activity.items()},
        "statistics": {key: _numeric(value) for key, value in statistics.items()},
        "locks": {key: _numeric(value) for key, value in locks.items()},
        "slow_queries": slow_queries,
        "blocked": blocked,
        "tables": table_counts,
        "cache_hit_ratio": round(cache_hit, 4) if cache_hit is not None else None,
    }


def process_metrics() -> dict:
    """Memória/CPU do processo da API. Degrada sem ``psutil`` instalado."""

    payload: dict[str, Any] = {"pid": os.getpid(), "available": False}
    try:
        import psutil  # import tardio: dependência opcional
    except ImportError:
        payload["reason"] = "psutil não instalado; memória do processo indisponível."
        return payload
    try:
        process = psutil.Process(os.getpid())
        with process.oneshot():
            memory = process.memory_info()
            payload.update(
                {
                    "available": True,
                    "rss_mb": round(memory.rss / (1024 * 1024), 2),
                    "vms_mb": round(memory.vms / (1024 * 1024), 2),
                    "cpu_percent": process.cpu_percent(interval=None),
                    "threads": process.num_threads(),
                    "open_files": _safe_count(process.open_files),
                    "connections": _safe_count(lambda: process.net_connections(kind="tcp")),
                    "started_at": process.create_time(),
                }
            )
        virtual = psutil.virtual_memory()
        payload["system"] = {
            "memory_total_mb": round(virtual.total / (1024 * 1024), 2),
            "memory_available_mb": round(virtual.available / (1024 * 1024), 2),
            "memory_percent": virtual.percent,
            "cpu_percent": psutil.cpu_percent(interval=None),
        }
    except Exception as exc:  # pragma: no cover - ambiente sem permissão
        logging.debug("Dev Observatory: métricas de processo indisponíveis", exc_info=True)
        payload["reason"] = f"Métricas de processo indisponíveis: {exc}"
    return payload


def _safe_count(getter) -> int | None:
    try:
        return len(getter())
    except Exception:
        return None
