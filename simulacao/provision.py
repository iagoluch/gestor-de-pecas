"""Cadastro necessário para a fábrica simulada existir.

Aqui só entra **cadastro**, nunca execução. A fronteira da seção 9 é literal:
apontamento, evento, participação e quantidade nascem exclusivamente da API.
O que este módulo garante é a identidade dos operadores simulados, os crachás e
o padrão de cotas dos produtos sintéticos — as três coisas sem as quais o fluxo
homologado não pode ser exercido.

As credenciais dos perfis ``sim_*`` são rotacionadas pela própria função de
hash da aplicação (``Database._hash_senha``), restritas a nomes que começam com
``sim_`` e nunca registradas em log ou artefato.
"""

from __future__ import annotations

from dataclasses import dataclass
import sys
from typing import Iterable

from simulacao.config import PROJECT_ROOT


if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


SIM_USER_PREFIX = "sim_"


@dataclass
class ResultadoProvisionamento:
    usuarios_criados: list[str]
    usuarios_atualizados: list[str]
    usuarios_recusados: list[str]


def _database():
    from app.database.database import Database

    return Database(auto_migrate=False)


def garantir_usuarios(
    perfis: dict[str, str], senha: str
) -> ResultadoProvisionamento:
    """Garante que cada perfil ``sim_*`` exista e aceite a senha da execução.

    ``perfis`` mapeia ``nome_de_login -> nivel``. Um nome fora do prefixo
    ``sim_`` é recusado: a simulação não mexe em credenciais de usuários que não
    pertencem a ela.
    """

    criados: list[str] = []
    atualizados: list[str] = []
    recusados: list[str] = []
    database = _database()
    try:
        existentes = {
            str(row["nome"]): row for row in (database.listar_usuarios() or [])
        }
        for login, nivel in perfis.items():
            if not login.startswith(SIM_USER_PREFIX):
                recusados.append(login)
                continue
            if login not in existentes:
                if database.criar_usuario(login, senha, nivel) is not None:
                    criados.append(login)
                continue
            if database.autenticar_usuario(login, senha):
                continue
            with database.connection() as connection, connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE usuarios SET senha_hash = %s, nivel = %s, ativo = TRUE WHERE nome = %s",
                    (database._hash_senha(senha), nivel, login),
                )
            atualizados.append(login)
    finally:
        database.close()
    return ResultadoProvisionamento(criados, atualizados, recusados)


async def garantir_crachas(sessao, crachas: Iterable[dict]) -> dict:
    """Cadastra os crachás da simulação pela tela de gestão (API canônica)."""

    resultado = {"criados": [], "falhas": []}
    for item in crachas:
        resposta = await sessao.call(
            "POST",
            "/management/badges",
            json={
                "cracha": item["cracha"],
                "nome": item["nome"],
                "ativo": True,
                "autorizador_retrabalho": bool(item.get("autorizador_retrabalho")),
            },
            action="cadastro_cracha",
            expect=(),
        )
        if resposta.ok:
            resultado["criados"].append(item["cracha"])
        else:
            resultado["falhas"].append(
                {"cracha": item["cracha"], "status": resposta.status, "code": resposta.code}
            )
    return resultado


async def garantir_template_qualidade(sessao, produto: str, cotas: list[dict]) -> bool:
    """Cadastra o padrão de cotas do produto pela própria tela da Qualidade.

    Sem template numérico o portão Setup/Qualidade recusa a liberação do lote
    (``primeira_peca_checklist_ausente``) — e é justamente a faixa
    ``referência ± margem`` que a seção 12 manda exercitar nos cinco casos.
    """

    resposta = await sessao.call(
        "POST",
        "/quality/templates",
        json={"produto": produto, "cotas": cotas},
        action="cadastro_template_qualidade",
        expect=(),
        registrar=False,
    )
    return resposta.ok
