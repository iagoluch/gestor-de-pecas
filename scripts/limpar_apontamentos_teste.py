#!/usr/bin/env python3
"""Zera fatos operacionais no PostgreSQL TESTE, preservando os cadastros.

Execute na raiz do Gestor de Peças:
    python scripts/limpar_apontamentos_teste.py
    python scripts/limpar_apontamentos_teste.py --apply

A prévia não altera dados. A aplicação valida o banco de destino, recusa
simulador ativo, faz backup CSV (ZIP) consistente e executa TRUNCATE RESTRICT
transacional. Não usa CASCADE, não apaga OPs/produtos/recursos/usuários.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import json
import logging
import os
from pathlib import Path
import sys
import zipfile

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

EXPECTED_DB = "gestor_pecas_test"
ADVISORY_KEY = "gestor:simulador-turno:v1"  # Mesma trava de fabrica_turno_real.py.

# Fatos de execução/estado. Nenhum cadastro de OP, produto ou recurso.
BASE_FACT_TABLES = frozenset({
    "apontamentos_operacionais",
    "eventos_apontamento_operador",
    "eventos_estado_recurso",
    "eventos_quantidade_producao",
    "participacoes_operador",
    "sessoes_recurso",
    "apontamentos_corte",
    "eventos_destaque_tarefa",
    "qualidade_primeira_peca",
    "qualidade_inspecoes",
    "alertas_internos",
})
# Exclusivamente tabelas dependentes de fatos, para não deixar vínculos soltos.
# Qualquer FK nova fora desta lista bloqueia a limpeza, em vez de expandi-la.
ALLOWED_DEPENDENTS = frozenset({
    "operadores_evento_apontamento",
    "rateios_tempo_op",
    "totvs_outbox",
    "totvs_outbox_attempts",
    "qualidade_primeira_peca_autorizacoes",
    "qualidade_rnc",
    "qualidade_pecas_inspecionadas",
    "qualidade_resultados_cota",
})
REQUIRED_TABLES = frozenset({
    "apontamentos_operacionais",
    "eventos_apontamento_operador",
    "eventos_estado_recurso",
    "eventos_quantidade_producao",
})


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Prévia/limpeza transacional dos apontamentos no banco gestor_pecas_test."
    )
    parser.add_argument("--apply", action="store_true", help="APAGA fatos operacionais do TESTE depois do backup.")
    parser.add_argument("--backup-dir", type=Path,
                        default=PROJECT_ROOT / "simulation_runs" / "backups_limpeza",
                        help="Diretório onde guardar ZIP dos dados removidos.")
    return parser.parse_args(argv)


def load_dsn():
    from dotenv import load_dotenv
    from psycopg.conninfo import conninfo_to_dict
    load_dotenv(PROJECT_ROOT / ".env", override=False)
    dsn = os.environ.get("TEST_DATABASE_URL", "").strip()
    if not dsn:
        raise RuntimeError("TEST_DATABASE_URL não configurada. Execução recusada.")
    values = conninfo_to_dict(dsn)
    dbname = str(values.get("dbname") or "")
    if dbname.casefold() != EXPECTED_DB:
        raise RuntimeError(f"Destino recusado: banco '{dbname}'. Esperado: {EXPECTED_DB}.")
    configured_expected = os.getenv("GESTOR_EXPECTED_DATABASE", "").strip()
    if configured_expected and configured_expected.casefold() != EXPECTED_DB:
        raise RuntimeError("GESTOR_EXPECTED_DATABASE diverge do banco TESTE permitido.")
    prod = os.getenv("DATABASE_URL", "").strip()
    if prod and conninfo_to_dict(prod) == values:
        raise RuntimeError("TEST_DATABASE_URL coincide com DATABASE_URL; execução recusada.")
    return dsn


def get_existing_tables(cur):
    cur.execute("""
        SELECT c.relname
        FROM pg_catalog.pg_class c
        JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p')
    """)
    return {row[0] for row in cur.fetchall()}


def get_fk_edges(cur):
    # (tabela dependente, tabela referenciada, nome constraint, regra delete).
    cur.execute("""
        SELECT child.relname, parent.relname, c.conname, c.confdeltype
        FROM pg_catalog.pg_constraint c
        JOIN pg_catalog.pg_class child ON child.oid = c.conrelid
        JOIN pg_catalog.pg_namespace cn ON cn.oid = child.relnamespace
        JOIN pg_catalog.pg_class parent ON parent.oid = c.confrelid
        JOIN pg_catalog.pg_namespace pn ON pn.oid = parent.relnamespace
        WHERE c.contype = 'f' AND cn.nspname = 'public' AND pn.nspname = 'public'
    """)
    return cur.fetchall()


def resolve_tables(existing, edges):
    missing = REQUIRED_TABLES - existing
    if missing:
        raise RuntimeError("Esquema incompleto; faltam: " + ", ".join(sorted(missing)))
    selected = set(BASE_FACT_TABLES & existing)
    while True:
        new = set()
        unexpected = []
        for child, parent, name, _action in edges:
            if parent not in selected or child in selected:
                continue
            if child in ALLOWED_DEPENDENTS:
                new.add(child)
            else:
                unexpected.append((child, parent, name))
        if unexpected:
            details = "; ".join(f"{c} -> {p} ({fk})" for c, p, fk in sorted(set(unexpected)))
            raise RuntimeError(
                "Nova tabela dependente fora da lista segura: " + details + ". Nada foi excluído."
            )
        if not new - selected:
            return sorted(selected)
        selected.update(new)


def count_rows(cur, names):
    from psycopg import sql
    counts = {}
    for table in names:
        cur.execute(sql.SQL("SELECT COUNT(*) FROM {}") .format(sql.Identifier("public", table)))
        counts[table] = int(cur.fetchone()[0])
    return counts


def snapshot(cur, names, counts, output):
    """CSV por tabela, sob os mesmos locks usados na exclusão."""
    from psycopg import sql
    output.parent.mkdir(parents=True, exist_ok=True)
    partial = output.with_suffix(".partial")
    try:
        with zipfile.ZipFile(partial, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=5,
                             allowZip64=True) as archive:
            manifest = {
                "database": EXPECTED_DB,
                "captured_at": datetime.now().astimezone().isoformat(),
                "schema": "public",
                "tables": counts,
                "notice": "Backup CSV dos fatos operacionais antes da limpeza; cadastros não incluídos.",
            }
            archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
            for table in names:
                query = sql.SQL("COPY {} TO STDOUT WITH (FORMAT CSV, HEADER TRUE)").format(
                    sql.Identifier("public", table)
                )
                with archive.open(f"{table}.csv", "w") as sink:
                    with cur.copy(query) as copy:
                        while chunk := copy.read():
                            # psycopg 3 COPY.read() normalmente devolve memoryview,
                            # que e binario e nao possui .encode().
                            if isinstance(chunk, memoryview):
                                sink.write(chunk.tobytes())
                            elif isinstance(chunk, bytes):
                                sink.write(chunk)
                            elif isinstance(chunk, str):
                                sink.write(chunk.encode("utf-8"))
                            else:
                                raise TypeError(
                                    f"COPY retornou bloco inesperado: {type(chunk).__name__}"
                                )
        os.replace(partial, output)
    finally:
        if partial.exists():
            partial.unlink()


def run(argv=None):
    args = parse_args(argv)
    try:
        import psycopg
        from psycopg import sql
        dsn = load_dsn()
        # Verificação real do destino; nunca confiar apenas no nome da variável.
        with psycopg.connect(dsn, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT current_database()")
                current = cur.fetchone()[0]
                if str(current).casefold() != EXPECTED_DB:
                    raise RuntimeError(f"current_database()={current!r}; alvo recusado.")
                cur.execute("SELECT pg_try_advisory_lock(hashtext(%s))", (ADVISORY_KEY,))
                if not cur.fetchone()[0]:
                    raise RuntimeError(
                        "O simulador de turno está em execução. Pare seu terminal antes de limpar."
                    )
                try:
                    existing = get_existing_tables(cur)
                    edges = get_fk_edges(cur)
                    tables = resolve_tables(existing, edges)
                    if not args.apply:
                        counts = count_rows(cur, tables)
                        print(f"\nPRÉVIA — Banco: {EXPECTED_DB}. Nenhum dado foi alterado.")
                        for table in tables:
                            print(f"  {table:<42} {counts[table]:>10}")
                        print(f"TOTAL: {sum(counts.values())} registros em {len(tables)} tabelas.")
                        print("\nPara apagar esses fatos operacionais (com backup ZIP automático):")
                        print(r"  .\.venv\Scripts\python.exe scripts\limpar_apontamentos_teste.py --apply")
                        print("Cadastros de OP, operações, recursos, produtos, usuários e calendários são preservados.")
                        return 0

                    # Única transação para bloquear gravações durante a cópia e o TRUNCATE.
                    # TRUNCATE ... RESTRICT (sem CASCADE) falha se existir dependência nova.
                    with conn.transaction():
                        cur.execute("SET LOCAL lock_timeout = '5s'")
                        cur.execute("SET LOCAL statement_timeout = '0'")
                        targets = sql.SQL(", ").join(sql.Identifier("public", t) for t in tables)
                        cur.execute(sql.SQL("LOCK TABLE {} IN ACCESS EXCLUSIVE MODE").format(targets))
                        counts = count_rows(cur, tables)
                        total = sum(counts.values())
                        if total == 0:
                            print("Banco de TESTE já está limpo. Nenhum registro foi excluído.")
                            return 0
                        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
                        backup_path = args.backup_dir.resolve() / f"backup_apontamentos_{stamp}.zip"
                        print(f"Banco TESTE confirmado. Preparando backup de {total} registros...")
                        snapshot(cur, tables, counts, backup_path)
                        print(f"Backup criado: {backup_path}")
                        cur.execute(sql.SQL("TRUNCATE TABLE {} CONTINUE IDENTITY RESTRICT").format(targets))
                        remain = count_rows(cur, tables)
                        if any(remain.values()):
                            raise RuntimeError("Contagem pós-limpeza não é zero; rollback executado.")
                    print(f"LIMPEZA CONCLUÍDA: {total} registros removidos de {len(tables)} tabelas.")
                    print("Servidor e Andon não foram reiniciados. Cadastros preservados.")
                    return 0
                finally:
                    cur.execute("SELECT pg_advisory_unlock(hashtext(%s))", (ADVISORY_KEY,))
    except Exception as exc:
        logging.error("LIMPEZA RECUSADA / NÃO CONCLUÍDA: %s", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(run())
