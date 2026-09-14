"""Preenche `catalogo_status_recursos.planejado` no banco de TESTE.

Contexto (Wave 6A): a coluna `planejado` estava NULL nas 84 linhas do
catálogo de status de recurso (origem PCFactory/TOTVS `TBLResourceStatus.xls`)
no banco `gestor_pecas_test`. A classificação central de parada
(`ManufacturingRules.classify_stop`) já dá prioridade a essa coluna sobre o
grupo, mas sem dado ela caía sempre no fallback pelo grupo `0002`.

A decisão de negócio já está documentada em
`mes/domain/manufacturing_rules.py` (comentário de `PLANNED_STOP_GROUP_CODES`):
o grupo `0002 — PARADA PROGRAMADA` reúne exatamente os motivos planejados
(FORA DE TURNO, PAUSA PARA CAFÉ, INTERVALO, REUNIÃO, LIMPEZA, MANUTENÇÃO
PREVENTIVA, férias, folga etc.). Todo o resto — inclusive
`0001-PRODUÇÃO/Falta de Apontamento` e `0006-PARADA NÃO PLANEJADA/AGUARDANDO
OP` — é não planejado. Este script apenas materializa essa regra já aprovada
pela Manufatura na coluna `planejado`, sem inventar critério novo.

Uso::

    python scripts/preencher_planejado_catalogo_status.py --dry-run
    python scripts/preencher_planejado_catalogo_status.py --confirmar gestor_pecas_test
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

import psycopg
from psycopg.rows import dict_row

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.database.config import load_postgres_config  # noqa: E402

EXPECTED_DATABASE = "gestor_pecas_test"
PLANNED_GROUP_CODE = "0002"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--confirmar",
        metavar="NOME_BANCO",
        help="Nome literal do banco de teste para confirmar a execução real.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Mostra o que seria alterado sem gravar.",
    )
    args = parser.parse_args()

    cfg = load_postgres_config(testing=True)

    with psycopg.connect(cfg.dsn, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT current_database()")
            actual_db = cur.fetchone()["current_database"]
            if actual_db != EXPECTED_DATABASE:
                print(
                    f"Recusado: banco ativo '{actual_db}' != '{EXPECTED_DATABASE}'.",
                    file=sys.stderr,
                )
                return 1

            cur.execute(
                "SELECT codigo, nome, grupo_codigo, planejado FROM catalogo_status_recursos ORDER BY codigo"
            )
            rows = cur.fetchall()
            to_true = [r for r in rows if str(r["grupo_codigo"] or "").strip() == PLANNED_GROUP_CODE]
            to_false = [r for r in rows if str(r["grupo_codigo"] or "").strip() != PLANNED_GROUP_CODE]

            print(f"Banco: {actual_db} | total linhas: {len(rows)}")
            print(f"planejado=true (grupo {PLANNED_GROUP_CODE}): {len(to_true)}")
            for r in to_true:
                print(f"  {r['codigo']:>6} {r['nome']}")
            print(f"planejado=false (demais grupos): {len(to_false)}")
            for r in to_false:
                print(f"  {r['codigo']:>6} {r['nome']} (grupo {r['grupo_codigo']})")

            if args.dry_run:
                print("\n--dry-run: nenhuma gravação realizada.")
                return 0

            if args.confirmar != EXPECTED_DATABASE:
                print(
                    "\nExecução real exige --confirmar gestor_pecas_test.",
                    file=sys.stderr,
                )
                return 1

            cur.execute(
                "UPDATE catalogo_status_recursos SET planejado = (grupo_codigo = %s)",
                (PLANNED_GROUP_CODE,),
            )
            conn.commit()
            print(f"\nUPDATE aplicado: {cur.rowcount} linhas.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
