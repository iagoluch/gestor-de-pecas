"""Solda em três níveis: mapa de produtos/subconjuntos por setor (só admin).

Leitura e cadastro. Nada aqui inicia tempo ou mexe em apontamento: o
subconjunto só filtra a fila da estação física (ver ``/operator/workbench``).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi import Path as ApiPath
from pydantic import BaseModel, Field

from app.core.operator_sectors import WELDING_FAMILY_SECTORS
from app.database.solda_mapa_repository import SoldaMapaConflito
from backend.api.database import get_database
from backend.api.dependencies.auth import require_admin_user, require_csrf
from backend.api.dependencies.clock import request_now_func
from backend.api.errors import AppError
from backend.api.schemas.auth import SessionUser
from mes.services.change_audit import auditar
from mes.services.operator_flow import OperatorFlowService
from mes.services.solda_mapa import fila_do_setor, montar_mapa

router = APIRouter(prefix="/solda-mapa", tags=["Solda: mapa de produtos"])

_SETORES = {nome: (estacoes, niveis) for nome, estacoes, niveis in WELDING_FAMILY_SECTORS}


class CadastroRequest(BaseModel):
    nome: str = Field(min_length=1, max_length=120)
    codigo: str = Field(min_length=1, max_length=60)
    ordem: int = Field(default=0, ge=0, le=9999)


class EdicaoRequest(BaseModel):
    nome: str | None = Field(default=None, min_length=1, max_length=120)
    codigo: str | None = Field(default=None, min_length=1, max_length=60)
    ativo: bool | None = None
    ordem: int | None = Field(default=None, ge=0, le=9999)


class VinculoRequest(BaseModel):
    codigo_item: str = Field(min_length=1, max_length=60)
    subconjunto_id: int | None = Field(default=None, ge=1)


def _setor(setor: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    if setor not in _SETORES:
        raise AppError("solda_setor_invalido", "Setor da Solda não encontrado.", status_code=404)
    return _SETORES[setor]


def _texto(valor: str, campo: str) -> str:
    valor = valor.strip()
    if not valor:
        raise AppError("solda_campo_vazio", f"Preencha o campo {campo}.", status_code=422)
    return valor


def _gravar(acao):
    try:
        return acao()
    except SoldaMapaConflito as error:
        raise AppError(
            "solda_codigo_repetido", "Esse código já está cadastrado nesse lugar.", status_code=409
        ) from error


def _existe(registro, mensagem):
    if registro is None:
        raise AppError("solda_nao_encontrado", mensagem, status_code=404)
    return registro


def _estacoes(estacoes, niveis):
    """Uma conta por estação (Aço, Alumínio, Robô) ou uma conta para vários recursos."""

    if len(niveis) == len(estacoes):
        return [{"level": n, "resources": [e]} for n, e in zip(niveis, estacoes)]
    return [{"level": niveis[0], "resources": list(estacoes)}]


@router.get("/{setor}")
def mapa_do_setor(
    request: Request,
    setor: str = ApiPath(min_length=1, max_length=60),
    user: SessionUser = Depends(require_admin_user),
    database=Depends(get_database),
):
    estacoes, niveis = _setor(setor)
    service = OperatorFlowService(database, user.name, now_func=request_now_func(request))
    fila = fila_do_setor(service, setor, estacoes)
    return {
        "setor": setor,
        "estacoes": _estacoes(estacoes, niveis),
        **montar_mapa(database.listar_solda_mapa(setor), fila),
    }


@router.post("/{setor}/produtos", dependencies=[Depends(require_csrf)])
def criar_produto(
    payload: CadastroRequest,
    setor: str = ApiPath(min_length=1, max_length=60),
    user: SessionUser = Depends(require_admin_user),
    database=Depends(get_database),
):
    _setor(setor)
    nome, codigo = _texto(payload.nome, "nome"), _texto(payload.codigo, "código")
    novo = _gravar(lambda: database.criar_solda_produto(setor, nome, codigo, payload.ordem, user.name))
    auditar(database, user, "solda_produto", str(novo["id"]), depois=novo)
    return novo


@router.put("/produtos/{produto_id}", dependencies=[Depends(require_csrf)])
def editar_produto(
    payload: EdicaoRequest,
    produto_id: int = ApiPath(ge=1),
    user: SessionUser = Depends(require_admin_user),
    database=Depends(get_database),
):
    antes = _existe(database.obter_solda_produto(produto_id), "Produto não encontrado.")
    campos = _campos(payload)
    depois = _gravar(lambda: database.atualizar_solda_produto(produto_id, campos))
    auditar(database, user, "solda_produto", str(produto_id), antes=antes, depois=depois)
    return depois


@router.post("/produtos/{produto_id}/subconjuntos", dependencies=[Depends(require_csrf)])
def criar_subconjunto(
    payload: CadastroRequest,
    produto_id: int = ApiPath(ge=1),
    user: SessionUser = Depends(require_admin_user),
    database=Depends(get_database),
):
    _existe(database.obter_solda_produto(produto_id), "Produto não encontrado.")
    nome, codigo = _texto(payload.nome, "nome"), _texto(payload.codigo, "código")
    novo = _gravar(
        lambda: database.criar_solda_subconjunto(produto_id, nome, codigo, payload.ordem, user.name)
    )
    auditar(database, user, "solda_subconjunto", str(novo["id"]), depois=novo)
    return novo


@router.put("/subconjuntos/{subconjunto_id}", dependencies=[Depends(require_csrf)])
def editar_subconjunto(
    payload: EdicaoRequest,
    subconjunto_id: int = ApiPath(ge=1),
    user: SessionUser = Depends(require_admin_user),
    database=Depends(get_database),
):
    antes = _existe(database.obter_solda_subconjunto(subconjunto_id), "Subconjunto não encontrado.")
    campos = _campos(payload)
    depois = _gravar(lambda: database.atualizar_solda_subconjunto(subconjunto_id, campos))
    antes = {k: v for k, v in antes.items() if k != "setor"}
    auditar(database, user, "solda_subconjunto", str(subconjunto_id), antes=antes, depois=depois)
    return depois


@router.post("/produtos/{produto_id}/vinculos", dependencies=[Depends(require_csrf)])
def criar_vinculo(
    payload: VinculoRequest,
    produto_id: int = ApiPath(ge=1),
    user: SessionUser = Depends(require_admin_user),
    database=Depends(get_database),
):
    _existe(database.obter_solda_produto(produto_id), "Produto não encontrado.")
    if payload.subconjunto_id is not None:
        sub = database.obter_solda_subconjunto(payload.subconjunto_id)
        if sub is None or sub["produto_id"] != produto_id:
            raise AppError(
                "solda_subconjunto_de_outro_produto",
                "Esse subconjunto não pertence a este produto.",
                status_code=422,
            )
    codigo = _texto(payload.codigo_item, "código do item")
    novo = _gravar(
        lambda: database.criar_solda_vinculo(produto_id, payload.subconjunto_id, codigo, user.name)
    )
    auditar(database, user, "solda_vinculo", str(novo["id"]), depois=novo)
    return novo


@router.delete("/vinculos/{vinculo_id}", dependencies=[Depends(require_csrf)])
def excluir_vinculo(
    vinculo_id: int = ApiPath(ge=1),
    user: SessionUser = Depends(require_admin_user),
    database=Depends(get_database),
):
    antes = _existe(database.excluir_solda_vinculo(vinculo_id), "Código não encontrado.")
    auditar(database, user, "solda_vinculo", str(vinculo_id), antes=antes, acao="excluir")
    return {"ok": True}


def _campos(payload: EdicaoRequest) -> dict:
    campos = payload.model_dump(exclude_none=True)
    for chave in ("nome", "codigo"):
        if chave in campos:
            campos[chave] = _texto(campos[chave], chave)
    return campos
