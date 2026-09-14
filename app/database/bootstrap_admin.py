"""Explicit command for creating the first PostgreSQL administrator."""

import argparse
import getpass
import os

from app.database.database import Database


def main(argv=None):
    parser = argparse.ArgumentParser(description="Cria o primeiro administrador do Gestor de Peças.")
    parser.add_argument("--name", required=True, help="Nome de login do administrador")
    args = parser.parse_args(argv)
    password = os.getenv("GESTOR_BOOTSTRAP_ADMIN_PASSWORD") or getpass.getpass("Senha inicial: ")
    if len(password) < 4:
        parser.error("a senha deve ter pelo menos 4 caracteres")

    db = Database()
    try:
        if db.listar_usuarios():
            parser.error("o banco já possui usuários; use a tela de Cadastro")
        user_id = db.criar_usuario(args.name.strip(), password, "admin")
        if not user_id:
            parser.error("não foi possível criar o administrador")
        print(f"Administrador inicial criado com ID {user_id}.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())

