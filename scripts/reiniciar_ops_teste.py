"""Reinicia OPs específicas no banco de TESTE, apagando só o histórico de execução.

Ao contrário de ``resetar_banco_teste.py`` (que limpa o banco inteiro), este
script apaga apenas os fatos de execução ligados a uma lista de códigos de OP,
preservando o cadastro (``catalogo_pcp_ops``, ``catalogo_operacoes_op``,
``catalogo_sigmanest_*``) para que a OP continue visível e selecionável pelo
operador, pronta para refazer o fluxo do zero.

``chamadas``/``chamada_visualizacoes`` não têm coluna de OP (schema
confirmado em ``app/database/migrations.py``) e por isso não são tocadas:
apagar por OP não é possível ali, e a tabela não bloqueia o reteste.
``tarefas`` e ``sessoes_recurso`` são entidades compartilhadas entre OPs e
também não são tocadas — só as linhas de junção/uso ligadas às OPs alvo.

Uso::

    python scripts/reiniciar_ops_teste.py --dry-run PCMITL01001 PCMIDN01017 PCMD8201001
    python scripts/reiniciar_ops_teste.py --confirmar gestor_pecas_test PCMITL01001 PCMIDN01017 PCMD8201001
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.database.config import load_postgres_config  # noqa: E402
from psycopg.conninfo import conninfo_to_dict  # noqa: E402

EXPECTED_DATABASE = "gestor_pecas_test"
PUBLIC_SCHEMA = "public"
STATEMENT_TIMEOUT = "30s"

# Ordem importa: qualidade_inspecoes antes de qualidade_rnc (pecas_inspecionadas
# tem rnc_id ON DELETE SET NULL, não CASCADE, então a ordem inversa deixaria a
# FK momentaneamente apontando para um RNC já removido dentro da mesma
# transação sem problema, mas mantemos a ordem lógica do fluxo por clareza).
# Tabelas com coluna "op":
OP_COLUMN_TABLES = (
    "apontamentos_operacionais",  # cascata: eventos_apontamento_operador -> operadores_evento_apontamento
    "historico",
    "eventos_estado_recurso",
    "eventos_quantidade_producao",
    "participacoes_operador",
    "rateios_tempo_op",
    "inconsistencias_dados",
)
# Tabelas com coluna "codigo_op":
CODIGO_OP_COLUMN_TABLES = (
    "qualidade_inspecoes",  # cascata: qualidade_pecas_inspecionadas -> qualidade_resultados_cota
    "qualidade_rnc",
    "qualidade_primeira_peca_autorizacoes",
    "qualidade_primeira_peca",
    "alertas_internos",
    "totvs_op_sync_requests",
    "op_por_tarefa",
)

# O template de cotas (qualidade_templates_produto/qualidade_cotas_template) é
# chaveado por produto_codigo, não por OP — é o "padrão" compartilhado por
# todas as OPs daquele produto. Só é seguro apagar com --incluir-templates,
# que primeiro confere que nenhuma OUTRA OP (fora da lista pedida) usa o
# mesmo produto, para não apagar o padrão de um produto ainda em uso.


def _validate_exact_name(value: str, *, source: str, expected: str) -> str:
    actual = str(value or "").strip()
    if actual != expected:
        raise RuntimeError(
            f"Execução recusada: {source} aponta para {actual!r}; "
            f"o valor obrigatório é exatamente {expected!r}."
        )
    return actual


def _test_config():
    environ = dict(__import__("os").environ)
    environ["GESTOR_EXPECTED_DATABASE"] = EXPECTED_DATABASE
    config = load_postgres_config(testing=True, environ=environ)
    configured_database = str(conninfo_to_dict(config.dsn).get("dbname") or "")
    _validate_exact_name(
        configured_database, source="TEST_DATABASE_URL", expected=EXPECTED_DATABASE
    )
    return config


def _count(cursor, table: str, column: str, ops: list[str]) -> int:
    cursor.execute(
        sql.SQL("SELECT COUNT(*) AS total FROM {}.{} WHERE {} = ANY(%s)").format(
            sql.Identifier(PUBLIC_SCHEMA), sql.Identifier(table), sql.Identifier(column)
        ),
        (ops,),
    )
    return int(cursor.fetchone()["total"])


def _delete(cursor, table: str, column: str, ops: list[str]) -> int:
    cursor.execute(
        sql.SQL("DELETE FROM {}.{} WHERE {} = ANY(%s)").format(
            sql.Identifier(PUBLIC_SCHEMA), sql.Identifier(table), sql.Identifier(column)
        ),
        (ops,),
    )
    return cursor.rowcount


def _produtos_das_ops(cursor, ops: list[str]) -> dict[str, str]:
    cursor.execute(
        "SELECT codigo_op, produto_codigo FROM public.catalogo_pcp_ops WHERE codigo_op = ANY(%s)",
        (ops,),
    )
    return {row["codigo_op"]: row["produto_codigo"] for row in cursor.fetchall()}


def _outras_ops_do_produto(cursor, produto: str, ops_alvo: list[str]) -> list[str]:
    cursor.execute(
        "SELECT codigo_op FROM public.catalogo_pcp_ops WHERE produto_codigo = %s",
        (produto,),
    )
    return [row["codigo_op"] for row in cursor.fetchall() if row["codigo_op"] not in ops_alvo]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ops", nargs="+", help="Códigos de OP a reiniciar")
    parser.add_argument("--dry-run", action="store_true", help="Só mostra as contagens, não apaga")
    parser.add_argument(
        "--incluir-templates",
        action="store_true",
        help="Também apaga o template de cotas (padrão/faixa) do produto de cada OP",
    )
    parser.add_argument(
        "--confirmar",
        metavar="NOME_DO_BANCO",
        help="Nome literal do banco para confirmar a execução real",
    )
    args = parser.parse_args()

    ops = [op.strip().upper() for op in args.ops]

    if not args.dry_run and args.confirmar != EXPECTED_DATABASE:
        print(
            f"Execução recusada: use --dry-run para revisar, ou "
            f"--confirmar {EXPECTED_DATABASE} para aplicar.",
            file=sys.stderr,
        )
        return 2

    config = _test_config()
    with psycopg.connect(config.dsn, row_factory=dict_row) as conn:
        with conn.cursor() as cursor:
            cursor.execute(f"SET statement_timeout = '{STATEMENT_TIMEOUT}'")
            cursor.execute("SELECT current_database() AS db")
            actual_db = cursor.fetchone()["db"]
            _validate_exact_name(actual_db, source="current_database()", expected=EXPECTED_DATABASE)

            print(f"Banco conectado: {actual_db}")
            print(f"OPs alvo: {', '.join(ops)}\n")

            plan: list[tuple[str, str]] = [(t, "op") for t in OP_COLUMN_TABLES] + [
                (t, "codigo_op") for t in CODIGO_OP_COLUMN_TABLES
            ]

            produto_por_op = _produtos_das_ops(cursor, ops) if args.incluir_templates else {}
            produtos = sorted(set(produto_por_op.values()))
            bloqueado_por_outra_op: dict[str, list[str]] = {}
            if args.incluir_templates:
                for produto in produtos:
                    outras = _outras_ops_do_produto(cursor, produto, ops)
                    if outras:
                        bloqueado_por_outra_op[produto] = outras
                produtos_seguros = [p for p in produtos if p not in bloqueado_por_outra_op]
                if bloqueado_por_outra_op:
                    print("Templates NÃO serão apagados (produto usado por outra OP fora da lista):")
                    for produto, outras in bloqueado_por_outra_op.items():
                        print(f"  {produto} -> também usado por: {', '.join(outras)}")

            if args.dry_run:
                print("Contagem de linhas que seriam apagadas (dry-run):")
                total = 0
                for table, column in plan:
                    count = _count(cursor, table, column, ops)
                    total += count
                    print(f"  {table:<45} {count}")
                if args.incluir_templates:
                    for produto in produtos_seguros:
                        cursor.execute(
                            "SELECT id FROM public.qualidade_templates_produto WHERE produto_codigo = %s",
                            (produto,),
                        )
                        row = cursor.fetchone()
                        if row is None:
                            continue
                        cursor.execute(
                            "SELECT COUNT(*) AS n FROM public.qualidade_cotas_template WHERE template_id = %s",
                            (row["id"],),
                        )
                        n_cotas = cursor.fetchone()["n"]
                        print(f"  template do produto {produto:<20} 1 template + {n_cotas} cota(s)")
                print(f"\nTotal: {total} linhas (mais cascatas automáticas por FK)")
                conn.rollback()
                return 0

            print("Apagando...")
            total = 0
            for table, column in plan:
                deleted = _delete(cursor, table, column, ops)
                total += deleted
                print(f"  {table:<45} {deleted} linha(s)")
            if args.incluir_templates:
                for produto in produtos_seguros:
                    cursor.execute(
                        "SELECT id FROM public.qualidade_templates_produto WHERE produto_codigo = %s",
                        (produto,),
                    )
                    row = cursor.fetchone()
                    if row is None:
                        continue
                    cursor.execute(
                        "DELETE FROM public.qualidade_cotas_template WHERE template_id = %s",
                        (row["id"],),
                    )
                    n_cotas = cursor.rowcount
                    cursor.execute(
                        "DELETE FROM public.qualidade_templates_produto WHERE id = %s",
                        (row["id"],),
                    )
                    total += n_cotas + cursor.rowcount
                    print(f"  template do produto {produto:<20} {n_cotas} cota(s) + 1 template")
            conn.commit()
            print(f"\nTotal apagado: {total} linhas. Cadastro (catalogo_pcp_ops etc.) preservado.")
            return 0


if __name__ == "__main__":
    raise SystemExit(main())
