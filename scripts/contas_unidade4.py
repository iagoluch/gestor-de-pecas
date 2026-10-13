"""Cria/ajusta as contas da unidade 4 (09/10/2026).

Cada pessoa vira uma conta com o nível do seu setor e Unidade = 4.
- Conta que já existe: troca nível e unidade.
- Conta que não existe: é criada.
- Com --aplicar, TODAS as contas do banco (as da lista e as demais) passam a ter
  a senha 123456 (pedido do usuário, 09/10/2026) e as sessões abertas caem.

Uso (precisa da API já reiniciada, para a migration 61 ter criado os níveis):

    python scripts/contas_unidade4.py             # só mostra o que faria
    python scripts/contas_unidade4.py --aplicar   # grava no banco do .env
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv

load_dotenv(PROJECT_ROOT / ".env", override=False)

from app.core.permissions import USER_LEVELS  # noqa: E402
from app.database.database import Database  # noqa: E402

UNIDADE = "4"
SENHA_INICIAL = "123456"

# login -> nível (o login segue o padrão das contas já existentes: minúsculo, sem acento)
CONTAS = {
    "fernando": "supervisor_caldeiraria",
    "lucas": "supervisor_almoxarifado_solda_pintura",
    "ze.mario": "supervisor_prototipo",
    "alan": "lider_dobra_corte",
    "tytio": "lider_usinagem",
    "murilo": "lider_serra",
    "bruno": "lider_pintura_almoxarifado",
    "jhonathan": "lider_solda",
    "sandro": "qualidade",
    "gabriel.fogaca": "manufatura",
    "lucas.santos": "manufatura",
    "michel.cardoso": "manufatura",
    "joao.thives": "manufatura",
    "joao.nery": "manufatura",
    "luan": "projetos_adm",
    "guilherme": "projetos_adm",
    "bruna": "pcp",
    "maria": "pcp",
    "adriano": "pcp",
    "felipe": "gerente_industrial",
    "alana": "melhoria_continua",
    "jose": "controladoria",
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--aplicar", action="store_true")
    aplicar = parser.parse_args().aplicar

    # Banco operacional (DATABASE_URL): é onde estão as contas reais.
    db = Database(dsn=os.environ["DATABASE_URL"])
    niveis = {*USER_LEVELS, *(n["nome"] for n in db.listar_niveis_personalizados() or [])}
    faltando = sorted({n for n in CONTAS.values() if n not in niveis})
    if faltando:
        sys.exit(f"Níveis inexistentes no banco (reinicie a API para migrar): {', '.join(faltando)}")

    por_nome = {u["nome"]: u for u in db.listar_usuarios() or []}
    for login, nivel in CONTAS.items():
        atual = por_nome.get(login)
        acao = "criar" if atual is None else "ajustar"
        print(f"{acao:8} {login:16} -> {nivel}  (unidade {UNIDADE})")
        if not aplicar:
            continue
        if atual is None:
            usuario_id = db.criar_usuario(login, SENHA_INICIAL, nivel)
        else:
            usuario_id = atual["id"]
            db.atualizar_nivel_usuario(usuario_id, nivel)
        db.atualizar_unidade_usuario(usuario_id, UNIDADE)
    if aplicar:
        todos = db.listar_usuarios() or []
        for usuario in todos:
            db.resetar_senha_usuario(usuario["id"], SENHA_INICIAL)
        print(f"\nSenha {SENHA_INICIAL} aplicada a {len(todos)} contas.")
    print("\nGravado." if aplicar else "\nSimulação: nada foi gravado. Use --aplicar.")


if __name__ == "__main__":
    main()
