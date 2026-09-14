"""Optional and explicit development seed; never runs during normal startup."""

import argparse
import os

from app.database.database import Database


def main(argv=None):
    parser = argparse.ArgumentParser(description="Carrega dados demonstrativos no PostgreSQL configurado.")
    parser.add_argument("--user", default="Desenvolvimento", help="Usuário administrativo de desenvolvimento")
    args = parser.parse_args(argv)
    password = os.getenv("GESTOR_DEV_PASSWORD")
    if not password or len(password) < 4:
        parser.error("defina GESTOR_DEV_PASSWORD com pelo menos 4 caracteres")

    db = Database()
    try:
        if not db.usuario_existe(args.user):
            db.criar_usuario(args.user, password, "admin")
        tarefa_id = db.inserir_tarefa("DEV-T100", material="Aço de demonstração", espessura=2.0)
        db.inserir_op_na_tarefa(tarefa_id, "DEV-OP100", "Peça demonstrativa", "Aguardando Dobra", 1)
        print("Seed de desenvolvimento aplicado explicitamente.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
