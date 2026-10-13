#!/usr/bin/env python3
"""Sincroniza SOMENTE cadastros do banco REAL para gestor_pecas_test.

A origem e aberta em modo read-only. Nunca copia apontamentos, senhas reais,
mensagens, chats, tokens, outbox ou historicos de auditoria.

  python scripts/sincronizar_cadastros_real_teste.py
  python scripts/sincronizar_cadastros_real_teste.py --apply --confirmar gestor_pecas_test

E uma atualizacao ADITIVA (upsert), nao um espelho destrutivo de todas as tabelas.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
from pathlib import Path
import secrets
import sys
from datetime import datetime
from zipfile import ZipFile, ZIP_DEFLATED

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

TARGET = "gestor_pecas_test"
SOURCE = "gestor_pecas"
LOCK = "gestor:simulador-turno:v1"
OUT = ROOT / "simulation_runs" / "sincronizacao_cadastros"
LOG = logging.getLogger("sync")

# Ordem das dependencias: tabelas-filhas nunca sao carregadas antes das tabelas-pai.
# id (surrogate key) nunca e transplantado, evitando colisao de PK no TESTE.
TABLES = (
    ("niveis_acesso", ("nome",)),
    ("calendarios_produtivos", ("codigo",)),
    ("catalogo_status_recursos", ("codigo",)),
    ("catalogo_recursos_pcfactory", ("codigo",)),
    ("parametros_turno", ("nome",)),
    ("catalogo_pcp_ops", ("codigo_op",)),
    ("catalogo_sigmanest_tarefas", ("codigo_tarefa",)),
    ("catalogo_sigmanest_programas", ("codigo_tarefa", "programa")),
    ("catalogo_sigmanest_ops", ("linha_hash",)),
    ("catalogo_sigmanest_planos_corte", ("plano_hash",)),
    ("tempo_padrao_manual", ("produto_codigo", "numero_operacao", "codigo_recurso")),
)
LATE_TABLES = (
    ("turnos_produtivos", ("calendario_codigo", "nome", "dia_semana", "hora_inicio")),
    ("qualidade_templates_produto", ("produto_codigo",)),
)
# Campos proibidos de transplantar (mesmo em tabelas de cadastro).
OMIT = {
    "tempo_padrao_manual": {"usuario_id"},
    "qualidade_templates_produto": {"criado_por", "atualizado_por"},
}
OPERATION_TABLE = "catalogo_operacoes_op"
USERS = "usuarios"
OPERATORS = "operadores_apontamento"
REPLACE_CONFIG = ("pausas_automaticas_setor", "excecoes_calendario_produtivo")
CHILDREN = ("intervalos_turno_produtivo", "qualidade_cotas_template")
ALL_TABLES = tuple(dict.fromkeys([
    *(x for x, _ in TABLES), USERS, OPERATORS, OPERATION_TABLE,
    *(x for x, _ in LATE_TABLES), *REPLACE_CONFIG, *CHILDREN,
]))


def options(argv=None):
    p = argparse.ArgumentParser(description="Cadastros REAL -> TESTE, sem copiar fatos operacionais.")
    p.add_argument("--apply", action="store_true", help="Aplica a sincronizacao no TESTE")
    p.add_argument("--confirmar", help="Deve ser literalmente gestor_pecas_test")
    p.add_argument("--sem-usuarios", action="store_true", help="Nao atualiza nem cria usuarios")
    return p.parse_args(argv)


def connect_urls():
    from dotenv import load_dotenv
    from psycopg.conninfo import conninfo_to_dict
    load_dotenv(ROOT / ".env", override=False)
    real = (os.getenv("DATABASE_URL") or "").strip()
    test = (os.getenv("TEST_DATABASE_URL") or "").strip()
    if not real or not test:
        raise RuntimeError("DATABASE_URL (REAL) e TEST_DATABASE_URL sao obrigatorios; nao informe as senhas no chat.")
    sr, st = conninfo_to_dict(real), conninfo_to_dict(test)
    if sr.get("dbname") != SOURCE or st.get("dbname") != TARGET:
        raise RuntimeError(f"Nomes recusados: origem deve ser '{SOURCE}' e destino '{TARGET}'.")
    if sr == st:
        raise RuntimeError("Origem e destino sao a mesma conexao.")
    return real, test


def columns(cursor, table):
    cursor.execute("""
      SELECT column_name, is_identity, is_generated
      FROM information_schema.columns
      WHERE table_schema='public' AND table_name=%s
      ORDER BY ordinal_position
    """, (table,))
    return {
        row["column_name"] for row in cursor.fetchall()
        if row["is_identity"] != "YES" and row["is_generated"] == "NEVER"
    }


def schema_check(src, dst):
    for table in ALL_TABLES:
        a, b = columns(src, table), columns(dst, table)
        if not a or not b:
            raise RuntimeError(f"Tabela ausente no REAL/TESTE: {table}; atualize as migrations antes de sincronizar.")
        if a != b:
            differences = sorted(a ^ b)
            raise RuntimeError(f"Schema divergente em {table}: {differences}. Atualize primeiro o banco de TESTE.")
    src.execute("SELECT MAX(version) AS v FROM public.schema_migrations")
    s = src.fetchone()["v"]
    dst.execute("SELECT MAX(version) AS v FROM public.schema_migrations")
    d = dst.fetchone()["v"]
    if str(s) != str(d):
        raise RuntimeError(f"Migrations divergentes (REAL={s}, TESTE={d}). Atualize o TESTE antes.")


def select_all(cursor, table):
    from psycopg import sql
    cursor.execute(sql.SQL("SELECT * FROM public.{}").format(sql.Identifier(table)))
    return [dict(row) for row in cursor.fetchall()]


def count(cursor, table):
    from psycopg import sql
    cursor.execute(sql.SQL("SELECT COUNT(*) AS n FROM public.{}").format(sql.Identifier(table)))
    return int(cursor.fetchone()["n"])


def bulk_upsert(src, dst, table, keys, *, rows=None, omit=(), predicate=None, keep=None):
    from psycopg import sql
    if rows is None:
        rows = select_all(src, table)
    if not rows:
        return 0
    fields = sorted((columns(src, table) & columns(dst, table)) - {"id", *omit})
    if keep is not None:
        fields = [field for field in fields if field in set(keep)]
    if not set(keys) <= set(fields):
        raise RuntimeError(f"Chave ausente em {table}: {keys}")
    updated = [x for x in fields if x not in keys]
    ins = sql.SQL("INSERT INTO public.{} ({}) VALUES ({}) ON CONFLICT ({}) {} ").format(
        sql.Identifier(table), sql.SQL(", ").join(map(sql.Identifier, fields)),
        sql.SQL(", ").join([sql.Placeholder()] * len(fields)),
        sql.SQL(", ").join(map(sql.Identifier, keys)),
        sql.SQL("WHERE ") + sql.SQL(predicate) if predicate else sql.SQL(""),
    )
    if updated:
        ins += sql.SQL("DO UPDATE SET ") + sql.SQL(", ").join(
            sql.SQL("{}=EXCLUDED.{}").format(sql.Identifier(c), sql.Identifier(c)) for c in updated
        )
    else:
        ins += sql.SQL("DO NOTHING")
    for row in rows:
        dst.execute(ins, tuple(row.get(x) for x in fields))
    return len(rows)


def random_password():
    return secrets.token_urlsafe(26)


def hash_password(raw):
    salt = secrets.token_bytes(32)
    digest = hashlib.pbkdf2_hmac("sha256", raw.encode("utf-8"), salt, 600_000)
    return f"pbkdf2_sha256$600000${salt.hex()}${digest.hex()}"


def sync_users(src, dst):
    from psycopg import sql
    src_cols = columns(src, USERS)
    fields = [x for x in ("nome", "nivel", "ativo", "unidade") if x in src_cols]
    if "nome" not in fields or "nivel" not in fields or "ativo" not in fields:
        raise RuntimeError("usuarios sem nome/nivel/ativo; schema inesperado")
    result, new = {}, []
    dst.execute("SELECT nome FROM public.usuarios")
    existing = {row["nome"] for row in dst.fetchall()}
    for row in select_all(src, USERS):
        name = row["nome"]
        if name not in existing:
            secret = random_password()
            payload = {x: row[x] for x in fields}
            payload["senha_hash"] = hash_password(secret)
            keys = list(payload)
            dst.execute(
                sql.SQL("INSERT INTO public.usuarios ({}) VALUES ({})").format(
                    sql.SQL(", ").join(map(sql.Identifier, keys)),
                    sql.SQL(", ").join([sql.Placeholder()] * len(keys)),
                ), tuple(payload.values()),
            )
            new.append({"usuario": name, "senha_temporaria_teste": secret})
            existing.add(name)
            result[name] = "criado"
        else:
            edits = [c for c in fields if c != "nome"]
            dst.execute(
                sql.SQL("UPDATE public.usuarios SET {} WHERE nome=%s").format(
                    sql.SQL(", ").join(sql.SQL("{}=%s").format(sql.Identifier(c)) for c in edits)
                ), tuple(row[c] for c in edits) + (name,),
            )
            result[name] = "atualizado"
    return len(result), new


def copy_replace(src, dst, table):
    from psycopg import sql
    rows = select_all(src, table)
    allowed = sorted(columns(src, table) & columns(dst, table) - {"id"})
    dst.execute(sql.SQL("DELETE FROM public.{}").format(sql.Identifier(table)))
    for row in rows:
        dst.execute(sql.SQL("INSERT INTO public.{} ({}) VALUES ({})").format(
            sql.Identifier(table), sql.SQL(", ").join(map(sql.Identifier, allowed)),
            sql.SQL(", ").join([sql.Placeholder()] * len(allowed)),
        ), tuple(row.get(c) for c in allowed))
    return len(rows)


def copy_mapped_children(src, dst, parent, child, parent_key, parent_id_field, unique_keys):
    from psycopg import sql
    src.execute(sql.SQL("SELECT {} FROM public.{}").format(sql.SQL(", ").join(map(sql.Identifier, ("id", *parent_key))), sql.Identifier(parent)))
    source_parent = {r["id"]: tuple(r[k] for k in parent_key) for r in src.fetchall()}
    dst.execute(sql.SQL("SELECT {} FROM public.{}").format(sql.SQL(", ").join(map(sql.Identifier, ("id", *parent_key))), sql.Identifier(parent)))
    target_parent = {tuple(r[k] for k in parent_key): r["id"] for r in dst.fetchall()}
    rows = select_all(src, child)
    fields = sorted(columns(src, child) & columns(dst, child) - {"id"})
    updates = [c for c in fields if c not in unique_keys]
    statement = sql.SQL("INSERT INTO public.{} ({}) VALUES ({}) ON CONFLICT ({}) DO UPDATE SET {}").format(
        sql.Identifier(child),sql.SQL(", ").join(map(sql.Identifier, fields)),
        sql.SQL(", ").join([sql.Placeholder()] * len(fields)),
        sql.SQL(", ").join(map(sql.Identifier, unique_keys)),
        sql.SQL(", ").join(sql.SQL("{}=EXCLUDED.{}").format(sql.Identifier(c),sql.Identifier(c)) for c in updates),
    )
    for row in rows:
        key = source_parent.get(row[parent_id_field])
        if key not in target_parent:
            raise RuntimeError(f"{child} referencia {parent} inexistente: {key}")
        row[parent_id_field] = target_parent[key]
        dst.execute(statement, tuple(row.get(c) for c in fields))
    return len(rows)


def backup_tables(cur, tables, stamp):
    """Snapshot CSV no disco antes da escrita. Nao substitui dump restauravel integral."""
    from psycopg import sql
    OUT.mkdir(parents=True, exist_ok=True)
    dest = OUT / f"cadastros_teste_antes_{stamp}.zip"
    partial = dest.with_suffix(".partial")
    try:
        with ZipFile(partial, "w", ZIP_DEFLATED, compresslevel=5, allowZip64=True) as z:
            z.writestr("LEIA-ME.txt", "Copia CSV antes de sincronizar. Inclui hashes de senhas de TESTE. Guarde com acesso restrito. Nao e pg_dump restauravel.\n")
            for table in tables:
                query = sql.SQL("COPY public.{} TO STDOUT WITH (FORMAT CSV, HEADER TRUE)").format(sql.Identifier(table))
                with z.open(table+".csv", "w") as stream:
                    with cur.copy(query) as cp:
                        while part := cp.read():
                            stream.write(part.tobytes() if isinstance(part, memoryview) else part.encode("utf-8") if isinstance(part, str) else bytes(part))
        partial.replace(dest)
        try: dest.chmod(0o600)
        except OSError: pass
        return dest
    finally:
        if partial.exists(): partial.unlink()


def run(argv=None):
    args = options(argv)
    from psycopg.rows import dict_row
    import psycopg
    if args.apply and args.confirmar != TARGET:
        raise RuntimeError(f"Para aplicar, use --apply --confirmar {TARGET}.")
    real_url, test_url = connect_urls()
    with (
        psycopg.connect(real_url, options="-c default_transaction_read_only=on", row_factory=dict_row) as real,
        psycopg.connect(test_url, row_factory=dict_row) as test,
    ):
        with real.cursor() as src, test.cursor() as dst:
            src.execute("SELECT current_database() AS d, current_setting('transaction_read_only') AS ro")
            sc = src.fetchone()
            dst.execute("SELECT current_database() AS d")
            dc = dst.fetchone()
            if sc["d"] != SOURCE or sc["ro"] != "on" or dc["d"] != TARGET:
                raise RuntimeError("Verificacao de identidade/permissoes REAL e TESTE recusada")
            schema_check(src, dst)
            print(f"ORIGEM: {SOURCE} (SOMENTE LEITURA) | DESTINO: {TARGET}")
            for table in ALL_TABLES:
                print(f"  {table:<43} REAL={count(src,table):>7} TESTE={count(dst,table):>7}")
            if not args.apply:
                print("\nPREVIA: nenhum dado alterado. Para executar:")
                print("  .\\scripts\\sincronizar_cadastros_real_teste.bat --apply --confirmar gestor_pecas_test")
                print("Senhas, sessoes, mensagens, Telegram, apontamentos e eventos NAO sao importados.")
                return 0
            dst.execute("SET LOCAL lock_timeout = '5s'")
            dst.execute("SET LOCAL statement_timeout = '120s'")
            dst.execute("SELECT pg_try_advisory_xact_lock(hashtext(%s)) AS ok", (LOCK,))
            if not dst.fetchone()["ok"]:
                raise RuntimeError("Simulador ativo. Pare-o antes da sincronizacao.")
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            backup = backup_tables(dst, ALL_TABLES, stamp)
            print(f"Backup de CADASTROS do TESTE criado: {backup}")
            changed = {}
            for table, keys in TABLES:
                changed[table] = bulk_upsert(src, dst, table, keys, omit=OMIT.get(table, ()))
            changed[USERS], credentials = (0, []) if args.sem_usuarios else sync_users(src, dst)
            # Sem importar Telegram nem contato privado.
            changed[OPERATORS] = bulk_upsert(
                src, dst, OPERATORS, ("cracha",),
                keep={"cracha", "nome", "ativo", "fonte", "autorizador_retrabalho", "criado_em"},
            )
            operations = select_all(src, OPERATION_TABLE)
            totvs = [r for r in operations if r.get("totvs_activity_id") is not None]
            legacy = [r for r in operations if r.get("totvs_activity_id") is None]
            changed[OPERATION_TABLE] = (
                bulk_upsert(src, dst, OPERATION_TABLE, ("codigo_op", "totvs_activity_id"),
                            rows=totvs, predicate="totvs_activity_id IS NOT NULL")
                + bulk_upsert(src, dst, OPERATION_TABLE,
                              ("codigo_op", "numero_operacao", "codigo_recurso"),
                              rows=legacy, predicate="totvs_activity_id IS NULL")
            )
            for table, keys in LATE_TABLES:
                changed[table] = bulk_upsert(src, dst, table, keys, omit=OMIT.get(table, ()))
            changed["intervalos_turno_produtivo"] = copy_mapped_children(
                src, dst, "turnos_produtivos", "intervalos_turno_produtivo",
                ("calendario_codigo", "nome", "dia_semana", "hora_inicio"), "turno_id",
                ("turno_id", "hora_inicio", "hora_fim"),
            )
            changed["qualidade_cotas_template"] = copy_mapped_children(
                src, dst, "qualidade_templates_produto", "qualidade_cotas_template",
                ("produto_codigo",), "template_id", ("template_id", "sequencia"),
            )
            for table in REPLACE_CONFIG:
                changed[table] = copy_replace(src, dst, table)
            credentials_path = None
            if credentials:
                OUT.mkdir(parents=True, exist_ok=True)
                credentials_path = OUT / f"novos_usuarios_teste_{stamp}.json"
                with credentials_path.open("x", encoding="utf-8") as file:
                    json.dump(credentials, file, ensure_ascii=False, indent=2)
                try: credentials_path.chmod(0o600)
                except OSError: pass
            # Saida do contexto faz COMMIT. Rollback automatico para erros anteriores.
            print("\nSINCRONIZACAO CONCLUIDA:")
            for table, n in changed.items():
                print(f"  {table:<43} {n}")
            if credentials_path:
                print(f"  Novas credenciais temporarias de TESTE: {credentials_path}")
                print("  Guarde com acesso restrito e apague depois de redefinir as senhas.")
            print("Cadastros locais nao encontrados no REAL foram preservados (upsert).")
            print("Proximo passo: limpar fatos operacionais do TESTE com o script existente.")
            return 0


def main():
    logging.basicConfig(level=logging.INFO)
    try:
        return run()
    except Exception as e:
        LOG.error("SINCRONIZACAO RECUSADA/ROLLBACK: %s", e)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
