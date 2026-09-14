"""Remove somente o banco dedicado, mediante confirmação nominal explícita.

Este script é entregue para uso futuro. A homologação não o executa, pois o
banco precisa permanecer disponível para auditoria manual.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

import psycopg
from psycopg import sql


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tests.homologacao_extrema.seed_homologacao_extrema import (  # noqa: E402
    TARGET_DATABASE,
    _load_dsns,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--drop", action="store_true", help="Autoriza a remoção do banco dedicado.")
    parser.add_argument("--confirm-name", default="", help="Repita exatamente o nome do banco-alvo.")
    args = parser.parse_args()
    if not args.drop:
        print(f"Modo seguro: o banco {TARGET_DATABASE} seria removido. Nenhuma ação executada.")
        return
    if args.confirm_name != TARGET_DATABASE:
        raise RuntimeError("Confirmação recusada: o nome informado não coincide exatamente com o alvo.")
    if "test" not in TARGET_DATABASE.casefold() or "homolog" not in TARGET_DATABASE.casefold():
        raise RuntimeError("Barreira de segurança: o alvo não parece ser de homologação.")
    _operational, _common_test, _target, maintenance = _load_dsns()
    with psycopg.connect(maintenance, autocommit=True) as connection:
        connection.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s AND pid <> pg_backend_pid()",
            (TARGET_DATABASE,),
        )
        connection.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(TARGET_DATABASE)))
    print(f"Banco dedicado removido: {TARGET_DATABASE}")


if __name__ == "__main__":
    main()
