"""Cria/remove um usuário efêmero para captura visual no banco isolado."""

from __future__ import annotations

import os
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.database.config import PostgresConfig  # noqa: E402
from app.database.database import Database  # noqa: E402
from tests.simulacao_historica_3_meses.seed_simulacao_historica import (  # noqa: E402
    TARGET_DATABASE,
    _safe_dsns,
)


def main() -> None:
    if len(sys.argv) != 4 or sys.argv[1] not in {"create", "delete"}:
        raise SystemExit("Uso: visual_test_user.py create|delete NOME NIVEL")
    action, name, level = sys.argv[1:]
    password = os.getenv("SIMULATION_VISUAL_PASSWORD", "")
    if action == "create" and len(password) < 24:
        raise RuntimeError("Senha efêmera de captura ausente ou curta.")

    _operational, _common_test, target_dsn, _maintenance, safe = _safe_dsns()
    if safe["target"]["dbname"].casefold() != TARGET_DATABASE.casefold():
        raise RuntimeError("Operação recusada: banco de simulação inesperado.")
    db = Database(config=PostgresConfig(dsn=target_dsn, min_pool_size=1, max_pool_size=2))
    try:
        if action == "create":
            db.criar_usuario(name, password, level)
        else:
            with db.connection() as connection, connection.cursor() as cursor:
                cursor.execute("DELETE FROM usuarios WHERE nome = %s", (name,))
        print(f"{action}:ok")
    finally:
        db.close()


if __name__ == "__main__":
    main()
