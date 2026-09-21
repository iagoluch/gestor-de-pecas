"""Limpa dados operacionais do banco oficial de TESTE do Gestor de Peças.

O script é intencionalmente restrito a ``gestor_pecas_test``. Ele preserva a
estrutura PostgreSQL e os dados de cadastro/configuração (usuários, crachás,
recursos, status, calendários, pausas, IA, relatórios, templates/desenhos da
Qualidade e mensagens de integração que não sejam ``ProductionOrder``).

Uso recomendado::

    python scripts/resetar_banco_teste.py --dry-run
    python scripts/resetar_banco_teste.py --confirmar gestor_pecas_test

Opções de preservação de OPs::

    # Preserva uma OU múltiplas OPs específicas
    python scripts/resetar_banco_teste.py --confirmar gestor_pecas_test --preservar-ops PCMIXQ01001
    python scripts/resetar_banco_teste.py --confirmar gestor_pecas_test --preservar-ops PCMIXQ01001,PCMIXQ01002

    # Automaticamente busca e preserva OPs fechadas no banco REAL (Protheus)
    python scripts/resetar_banco_teste.py --confirmar gestor_pecas_test --preservar-ops-fechadas-protheus

    # Combina: preserva tanto as OPs fechadas quanto as informadas
    python scripts/resetar_banco_teste.py --confirmar gestor_pecas_test \\
        --preservar-ops-fechadas-protheus --preservar-ops PCMIXQ01999

A limpeza efetiva exige a confirmação literal do nome do banco. Todas as
tabelas operacionais são truncadas na mesma transação, com locks limitados por
timeout. Envelopes ``ProductionOrder`` são removidos seletivamente da inbox
TOTVS, respeitando OPs a preservar; mensagens ``WhoIs`` e outras transações
permanecem.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import os
from pathlib import Path
import sys
from typing import Any, Iterable

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg.rows import dict_row


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.database.config import load_postgres_config  # noqa: E402
from app.database.migrations import EXPECTED_TABLES  # noqa: E402
from app.database.schema import SCHEMA_VERSION  # noqa: E402


EXPECTED_DATABASE = "gestor_pecas_test"
REAL_DATABASE = "gestor_pecas"
PUBLIC_SCHEMA = "public"
RESET_LOCK_ID = 874_210_324
LOCK_TIMEOUT = "5s"
STATEMENT_TIMEOUT = "60s"

# Projeções de planejamento e fatos de execução/homologação. A lista é
# explícita para impedir que uma tabela nova seja apagada por heurística.
TRUNCATE_TABLES = (
    # Wave 5. Primeira peça, autorização do responsável e alertas internos são
    # fatos de execução: sem truncá-los, uma OP reingerida herdaria o portão já
    # aprovado — ou o bloqueio — da execução anterior.
    "alertas_internos",
    "qualidade_primeira_peca_autorizacoes",
    "qualidade_primeira_peca",
    "apontamentos_corte",
    "apontamentos_operacionais",
    # Histórico de chamadas (fato de execução, igual a "historico"/
    # "eventos_sistema") e o marcador de "última vista" por usuário, que
    # referencia esse histórico e ficaria com IDs órfãos se ele sobrevivesse
    # à limpeza sozinho. O cadastro de quem pode ser chamado
    # (chamada_contatos, com nome/função/setores) continua protegido.
    "chamadas",
    "chamada_visualizacoes",
    "catalogo_operacoes_op",
    "catalogo_pcp_ops",
    "catalogo_sigmanest_ops",
    "catalogo_sigmanest_planos_corte",
    "catalogo_sigmanest_programas",
    "catalogo_sigmanest_tarefas",
    "eventos_apontamento_operador",
    "eventos_destaque_tarefa",
    "eventos_estado_recurso",
    "eventos_quantidade_producao",
    "eventos_sistema",
    "historico",
    "inconsistencias_dados",
    "op_por_tarefa",
    "operadores_evento_apontamento",
    "participacoes_operador",
    "qualidade_inspecoes",
    "qualidade_pecas_inspecionadas",
    "qualidade_resultados_cota",
    "qualidade_rnc",
    "rateios_tempo_op",
    "sessoes_recurso",
    "tarefas",
    "totvs_op_sync_requests",
    "totvs_outbox",
    "totvs_outbox_attempts",
)

# Esta tabela contém tanto envelopes operacionais de OP quanto mensagens de
# configuração/diagnóstico (por exemplo, WhoIs). Por isso ela não é truncada.
SELECTIVE_TABLE = "totvs_integration_messages"
SELECTIVE_TRANSACTION = "ProductionOrder"

# O manifesto de migrations é a fonte única para o schema conhecido. O reset
# compara exatamente essa lista antes de tocar em qualquer dado do TESTE.
KNOWN_TABLES = frozenset(EXPECTED_TABLES)
PROTECTED_TABLES = tuple(
    sorted(KNOWN_TABLES - frozenset(TRUNCATE_TABLES) - {SELECTIVE_TABLE})
)


@dataclass(frozen=True)
class DatabaseIdentity:
    host: str
    port: str
    database: str
    schema: str


def _validate_exact_name(value: str, *, source: str, expected: str) -> str:
    actual = str(value or "").strip()
    if actual != expected:
        raise RuntimeError(
            f"Execução recusada: {source} aponta para {actual!r}; "
            f"o valor obrigatório é exatamente {expected!r}."
        )
    return actual


def _test_config():
    configured_guard = str(os.environ.get("GESTOR_EXPECTED_DATABASE") or "").strip()
    if configured_guard:
        _validate_exact_name(
            configured_guard,
            source="GESTOR_EXPECTED_DATABASE",
            expected=EXPECTED_DATABASE,
        )
    environ = dict(os.environ)
    environ["GESTOR_EXPECTED_DATABASE"] = EXPECTED_DATABASE
    config = load_postgres_config(testing=True, environ=environ)
    configured_database = str(conninfo_to_dict(config.dsn).get("dbname") or "")
    _validate_exact_name(
        configured_database,
        source="TEST_DATABASE_URL",
        expected=EXPECTED_DATABASE,
    )
    if configured_database == REAL_DATABASE:  # defesa explícita e não heurística
        raise RuntimeError("Execução recusada: o banco REAL nunca pode ser limpo.")
    return config


def _real_config():
    # GESTOR_EXPECTED_DATABASE protege a conexão destrutiva de TESTE. A
    # conexão separada com o REAL é exclusivamente read-only e tem a própria
    # validação literal abaixo.
    environ = dict(os.environ)
    environ.pop("GESTOR_EXPECTED_DATABASE", None)
    config = load_postgres_config(testing=False, environ=environ)
    configured_database = str(conninfo_to_dict(config.dsn).get("dbname") or "")
    _validate_exact_name(
        configured_database,
        source="DATABASE_URL",
        expected=REAL_DATABASE,
    )
    return config


def _connect_read_only(dsn: str):
    """Abre a verificação do REAL com escrita proibida pelo PostgreSQL."""

    parsed = conninfo_to_dict(dsn)
    existing_options = str(parsed.get("options") or "").strip()
    read_only_option = "-c default_transaction_read_only=on"
    options = f"{existing_options} {read_only_option}".strip()
    return psycopg.connect(
        make_conninfo(dsn, options=options),
        row_factory=dict_row,
    )


def _identity(cursor, *, expected_database: str) -> DatabaseIdentity:
    cursor.execute(
        """
        SELECT current_database() AS database,
               current_schema() AS schema,
               inet_server_addr()::text AS host,
               inet_server_port()::text AS port
        """
    )
    row = cursor.fetchone()
    database = _validate_exact_name(
        row["database"],
        source="current_database()",
        expected=expected_database,
    )
    schema = _validate_exact_name(
        row["schema"],
        source="current_schema()",
        expected=PUBLIC_SCHEMA,
    )
    return DatabaseIdentity(
        host=str(row["host"] or "local socket"),
        port=str(row["port"] or "5432"),
        database=database,
        schema=schema,
    )


def _table_inventory(cursor) -> frozenset[str]:
    cursor.execute(
        """
        SELECT table_name
          FROM information_schema.tables
         WHERE table_schema = %s
           AND table_type = 'BASE TABLE'
        """,
        (PUBLIC_SCHEMA,),
    )
    return frozenset(str(row["table_name"]) for row in cursor.fetchall())


def _validate_current_model(cursor) -> None:
    actual_tables = _table_inventory(cursor)
    missing = sorted(KNOWN_TABLES - actual_tables)
    unexpected = sorted(actual_tables - KNOWN_TABLES)
    if missing or unexpected:
        details = []
        if missing:
            details.append("ausentes=" + ", ".join(missing))
        if unexpected:
            details.append("não revisadas=" + ", ".join(unexpected))
        raise RuntimeError(
            "Limpeza recusada: o modelo efetivo diverge da lista revisada ("
            + "; ".join(details)
            + "). Atualize o script após revisar as migrations."
        )

    cursor.execute("SELECT COALESCE(MAX(version), 0) AS version FROM schema_migrations")
    effective_version = int(cursor.fetchone()["version"])
    if effective_version != SCHEMA_VERSION:
        raise RuntimeError(
            "Limpeza recusada: schema efetivo "
            f"{effective_version}, aplicação {SCHEMA_VERSION}."
        )


def _count_tables(cursor, tables: Iterable[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for table in tables:
        cursor.execute(
            sql.SQL("SELECT COUNT(*) AS total FROM {}.{}").format(
                sql.Identifier(PUBLIC_SCHEMA),
                sql.Identifier(table),
            )
        )
        counts[table] = int(cursor.fetchone()["total"])
    return counts


def _count_selective(cursor, *, eligible: bool) -> int:
    operator = sql.SQL("=") if eligible else sql.SQL("IS DISTINCT FROM")
    cursor.execute(
        sql.SQL(
            "SELECT COUNT(*) AS total FROM {}.{} WHERE transaction {} %s"
        ).format(
            sql.Identifier(PUBLIC_SCHEMA),
            sql.Identifier(SELECTIVE_TABLE),
            operator,
        ),
        (SELECTIVE_TRANSACTION,),
    )
    return int(cursor.fetchone()["total"])


def _schema_snapshot(cursor) -> dict[str, tuple[tuple[Any, ...], ...]]:
    """Captura estrutura relevante, sem incluir o estado atual das sequences."""

    queries = {
        "tables": """
            SELECT c.relname, c.relkind, pg_get_userbyid(c.relowner)
              FROM pg_class c
              JOIN pg_namespace n ON n.oid = c.relnamespace
             WHERE n.nspname = %s AND c.relkind IN ('r', 'p')
             ORDER BY c.relname
        """,
        "columns": """
            SELECT table_name, ordinal_position, column_name, data_type,
                   udt_name, is_nullable, column_default, identity_generation
              FROM information_schema.columns
             WHERE table_schema = %s
             ORDER BY table_name, ordinal_position
        """,
        "constraints": """
            SELECT c.conrelid::regclass::text, c.conname, c.contype,
                   pg_get_constraintdef(c.oid, true)
              FROM pg_constraint c
              JOIN pg_namespace n ON n.oid = c.connamespace
             WHERE n.nspname = %s
             ORDER BY c.conrelid::regclass::text, c.conname
        """,
        "indexes": """
            SELECT tablename, indexname, indexdef
              FROM pg_indexes
             WHERE schemaname = %s
             ORDER BY tablename, indexname
        """,
        "sequences": """
            SELECT c.relname, s.seqtypid::regtype::text, s.seqstart,
                   s.seqincrement, s.seqmax, s.seqmin, s.seqcache, s.seqcycle
              FROM pg_sequence s
              JOIN pg_class c ON c.oid = s.seqrelid
              JOIN pg_namespace n ON n.oid = c.relnamespace
             WHERE n.nspname = %s
             ORDER BY c.relname
        """,
        "migrations": """
            SELECT version, descricao, applied_at
              FROM schema_migrations
             ORDER BY version
        """,
    }
    snapshot: dict[str, tuple[tuple[Any, ...], ...]] = {}
    for label, query in queries.items():
        if label == "migrations":
            cursor.execute(query)
        else:
            cursor.execute(query, (PUBLIC_SCHEMA,))
        snapshot[label] = tuple(tuple(row.values()) for row in cursor.fetchall())
    return snapshot


def _schema_summary(snapshot: dict[str, tuple[tuple[Any, ...], ...]]) -> dict[str, int]:
    return {label: len(rows) for label, rows in snapshot.items()}


def _lock_model(cursor) -> None:
    identifiers = [
        sql.SQL("{}.{}").format(sql.Identifier(PUBLIC_SCHEMA), sql.Identifier(table))
        for table in sorted(KNOWN_TABLES)
    ]
    cursor.execute(
        sql.SQL("LOCK TABLE {} IN ACCESS EXCLUSIVE MODE").format(
            sql.SQL(", ").join(identifiers)
        )
    )


def _truncate_operational(cursor) -> None:
    identifiers = [
        sql.SQL("{}.{}").format(sql.Identifier(PUBLIC_SCHEMA), sql.Identifier(table))
        for table in TRUNCATE_TABLES
    ]
    cursor.execute(
        sql.SQL("TRUNCATE TABLE {} RESTART IDENTITY").format(
            sql.SQL(", ").join(identifiers)
        )
    )


def _delete_production_order_messages(cursor, *, preserve_op_numbers: frozenset[str] | None = None) -> int:
    if not preserve_op_numbers:
        cursor.execute(
            sql.SQL("DELETE FROM {}.{} WHERE transaction = %s").format(
                sql.Identifier(PUBLIC_SCHEMA),
                sql.Identifier(SELECTIVE_TABLE),
            ),
            (SELECTIVE_TRANSACTION,),
        )
    else:
        # Deleta ProductionOrder messages EXCETO as que contêm números de OP preservados
        cursor.execute(
            sql.SQL(
                "DELETE FROM {}.{} WHERE transaction = %s AND NOT "
                "(payload_raw::jsonb->'ProductionOrder'->>'number' = ANY(%s))"
            ).format(
                sql.Identifier(PUBLIC_SCHEMA),
                sql.Identifier(SELECTIVE_TABLE),
            ),
            (SELECTIVE_TRANSACTION, list(preserve_op_numbers)),
        )
    return int(cursor.rowcount)


def _verify_real_snapshot(connection) -> tuple[DatabaseIdentity, dict[str, int]]:
    with connection.cursor() as cursor:
        identity = _identity(cursor, expected_database=REAL_DATABASE)
        cursor.execute("SHOW transaction_read_only")
        if str(cursor.fetchone()["transaction_read_only"]).casefold() != "on":
            raise RuntimeError("Verificação do banco REAL não está em modo somente leitura.")
        counts = _count_tables(cursor, ("tarefas", "catalogo_pcp_ops", "schema_migrations"))
    return identity, counts


def _get_closed_ops_from_real(connection) -> frozenset[str]:
    """Busca OPs com status de fechamento no banco REAL (Protheus)."""
    closed_ops: set[str] = set()
    try:
        with connection.cursor() as cursor:
            # Busca tarefas com data_finalizacao preenchida (indicando conclusão)
            cursor.execute(
                """
                SELECT DISTINCT op_por_tarefa.codigo_op
                FROM tarefas
                JOIN op_por_tarefa ON tarefas.id = op_por_tarefa.tarefa_id
                WHERE tarefas.data_finalizacao IS NOT NULL
                  AND tarefas.status IN ('Concluida', 'Finalizada', 'Fechada')
                ORDER BY op_por_tarefa.codigo_op
                """
            )
            for row in cursor.fetchall():
                op_number = str(row.get("codigo_op") or "").strip()
                if op_number:
                    closed_ops.add(op_number)
    except Exception as exc:
        print(
            f"Aviso: não foi possível buscar OPs fechadas do Protheus: {exc}",
            file=sys.stderr,
        )
    return frozenset(closed_ops)


def execute_reset(
    *, dry_run: bool, preserve_op_numbers: frozenset[str] | None = None
) -> dict[str, Any]:
    test_config = _test_config()
    real_config = _real_config()
    real_connection = _connect_read_only(real_config.dsn)
    test_connection = psycopg.connect(test_config.dsn, row_factory=dict_row)
    try:
        real_identity_before, real_counts_before = _verify_real_snapshot(real_connection)

        with test_connection.transaction():
            with test_connection.cursor() as cursor:
                test_identity = _identity(cursor, expected_database=EXPECTED_DATABASE)
                cursor.execute("SELECT set_config('lock_timeout', %s, true)", (LOCK_TIMEOUT,))
                cursor.execute(
                    "SELECT set_config('statement_timeout', %s, true)",
                    (STATEMENT_TIMEOUT,),
                )
                cursor.execute("SELECT pg_advisory_xact_lock(%s)", (RESET_LOCK_ID,))
                _validate_current_model(cursor)
                _lock_model(cursor)

                schema_before = _schema_snapshot(cursor)
                protected_before = _count_tables(cursor, PROTECTED_TABLES)
                protected_integration_before = _count_selective(cursor, eligible=False)
                removed = _count_tables(cursor, TRUNCATE_TABLES)
                total_production_orders = _count_selective(cursor, eligible=True)
                if preserve_op_numbers:
                    # Contagem de ProductionOrder que serão removidas (total - preservadas)
                    removed[SELECTIVE_TABLE] = total_production_orders - len(preserve_op_numbers)
                else:
                    removed[SELECTIVE_TABLE] = total_production_orders

                if dry_run:
                    # Não há mutação no dry-run. O contexto encerra a
                    # transação normalmente e libera os locks ao sair.
                    pass
                else:
                    _truncate_operational(cursor)
                    deleted_messages = _delete_production_order_messages(
                        cursor, preserve_op_numbers=preserve_op_numbers
                    )
                    expected_delete_count = (
                        removed[SELECTIVE_TABLE]
                        if not preserve_op_numbers
                        else removed[SELECTIVE_TABLE] - len(preserve_op_numbers)
                    )
                    if deleted_messages != expected_delete_count:
                        raise RuntimeError(
                            f"Contagem da inbox TOTVS mudou durante a transação; limpeza cancelada. "
                            f"Esperado: {expected_delete_count}, deletado: {deleted_messages}"
                        )

                    remaining = _count_tables(cursor, TRUNCATE_TABLES)
                    remaining[SELECTIVE_TABLE] = _count_selective(cursor, eligible=True)
                    leftovers = {table: count for table, count in remaining.items() if count}
                    if leftovers:
                        raise RuntimeError(
                            "Limpeza incompleta; transação cancelada: " + repr(leftovers)
                        )

                    protected_after = _count_tables(cursor, PROTECTED_TABLES)
                    protected_integration_after = _count_selective(cursor, eligible=False)
                    if protected_after != protected_before:
                        raise RuntimeError(
                            "Dados protegidos mudaram; transação cancelada."
                        )
                    if protected_integration_after != protected_integration_before:
                        raise RuntimeError(
                            "Mensagens TOTVS protegidas mudaram; transação cancelada."
                        )

                    schema_after = _schema_snapshot(cursor)
                    if schema_after != schema_before:
                        raise RuntimeError("O schema mudou durante a limpeza; transação cancelada.")

        # A conexão REAL permanece em transação somente leitura e repete o mesmo
        # snapshot; esta segunda leitura comprova que o script não a modificou.
        real_identity_after, real_counts_after = _verify_real_snapshot(real_connection)
        if real_identity_after != real_identity_before or real_counts_after != real_counts_before:
            raise RuntimeError("A verificação somente leitura do banco REAL divergiu.")

        if not dry_run:
            with test_connection.cursor() as cursor:
                confirmed_identity = _identity(cursor, expected_database=EXPECTED_DATABASE)
                _validate_current_model(cursor)
                schema_committed = _schema_snapshot(cursor)
                if schema_committed != schema_before:
                    raise RuntimeError("Schema divergente após o commit da limpeza.")
                committed_remaining = _count_tables(cursor, TRUNCATE_TABLES)
                committed_remaining[SELECTIVE_TABLE] = _count_selective(
                    cursor, eligible=True
                )
                if any(committed_remaining.values()):
                    raise RuntimeError(
                        "Dados operacionais reapareceram imediatamente após a limpeza."
                    )
            test_connection.rollback()
        else:
            confirmed_identity = test_identity

        result = {
            "mode": "dry-run" if dry_run else "applied",
            "test_target": confirmed_identity.__dict__,
            "real_read_only_target": real_identity_after.__dict__,
            "removed": removed,
            "removed_total": sum(removed.values()),
            "protected_counts": protected_before,
            "protected_integration_messages": protected_integration_before,
            "schema": _schema_summary(schema_before),
            "schema_version": SCHEMA_VERSION,
            "schema_intact": True,
        }
        if preserve_op_numbers:
            result["preserved_ops"] = sorted(preserve_op_numbers)
        return result
    finally:
        test_connection.close()
        real_connection.close()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Conta e valida tudo, sem remover registros.",
    )
    parser.add_argument(
        "--confirmar",
        metavar="BANCO",
        help=f"Para executar, informe literalmente {EXPECTED_DATABASE}.",
    )
    parser.add_argument("--json", action="store_true", help="Emite o resultado em JSON.")
    parser.add_argument(
        "--preservar-ops",
        metavar="OP1,OP2,OP3",
        help="Número de OPs a preservar, separadas por vírgula (ex: PCMIXQ01001,PCMIXQ01002).",
    )
    parser.add_argument(
        "--preservar-ops-fechadas-protheus",
        action="store_true",
        help="Automaticamente busca e preserva OPs fechadas no banco REAL (Protheus).",
    )
    return parser.parse_args()


def _print_result(result: dict[str, Any]) -> None:
    mode = "SIMULAÇÃO" if result["mode"] == "dry-run" else "LIMPEZA APLICADA"
    test = result["test_target"]
    real = result["real_read_only_target"]
    print(f"{mode}: {test['database']} em {test['host']}:{test['port']}")
    print(
        "Banco REAL verificado somente leitura: "
        f"{real['database']} em {real['host']}:{real['port']}"
    )
    print("\nTabelas operacionais e registros removidos:" if result["mode"] == "applied" else "\nTabelas operacionais e registros encontrados:")
    for table, count in result["removed"].items():
        suffix = " (somente ProductionOrder)" if table == SELECTIVE_TABLE else ""
        print(f"  {table:<40} {count:>8}{suffix}")
    print(f"  {'TOTAL':<40} {result['removed_total']:>8}")
    if result.get("preserved_ops"):
        print(
            f"\nOPs preservadas: {', '.join(sorted(result['preserved_ops']))}"
        )
    print(
        "\nMensagens de integração preservadas (não ProductionOrder): "
        f"{result['protected_integration_messages']}"
    )
    print(
        "Dados preservados: usuários/permissões, crachás, recursos/status, "
        "calendários/turnos/pausas, IA, relatórios, destinos, templates/cotas/"
        "desenhos da Qualidade e migrations."
    )
    schema = result["schema"]
    print(
        "Schema intacto confirmado: "
        f"versão {result['schema_version']}; {schema['tables']} tabelas; "
        f"{schema['columns']} colunas; {schema['constraints']} constraints; "
        f"{schema['indexes']} índices; {schema['sequences']} sequences."
    )


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="replace")
    args = _parse_args()
    if not args.dry_run and args.confirmar != EXPECTED_DATABASE:
        print(
            "Execução recusada: a limpeza exige "
            f"--confirmar {EXPECTED_DATABASE}.",
            file=sys.stderr,
        )
        return 2

    # Processa OPs a preservar
    preserve_op_numbers: frozenset[str] | None = None
    if args.preservar_ops or args.preservar_ops_fechadas_protheus:
        ops_to_preserve: set[str] = set()

        # Adiciona OPs informadas via argumento
        if args.preservar_ops:
            ops_list = [op.strip() for op in args.preservar_ops.split(",")]
            ops_to_preserve.update(op for op in ops_list if op)

        # Busca OPs fechadas do Protheus
        if args.preservar_ops_fechadas_protheus:
            try:
                real_config = _real_config()
                real_connection = _connect_read_only(real_config.dsn)
                try:
                    closed_ops = _get_closed_ops_from_real(real_connection)
                    ops_to_preserve.update(closed_ops)
                    if closed_ops:
                        print(
                            f"OPs fechadas no Protheus encontradas: {', '.join(sorted(closed_ops))}",
                            file=sys.stderr,
                        )
                finally:
                    real_connection.close()
            except Exception as exc:
                print(
                    f"Aviso: erro ao buscar OPs fechadas do Protheus: {exc}",
                    file=sys.stderr,
                )

        if ops_to_preserve:
            preserve_op_numbers = frozenset(ops_to_preserve)
            print(
                f"OPs a preservar: {', '.join(sorted(preserve_op_numbers))}",
                file=sys.stderr,
            )

    try:
        result = execute_reset(dry_run=args.dry_run, preserve_op_numbers=preserve_op_numbers)
    except Exception as exc:
        print(f"Falha segura: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    else:
        _print_result(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
