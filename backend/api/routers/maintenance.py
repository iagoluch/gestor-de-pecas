"""Sugestões de manutenção: parada NÃO planejada de manutenção corretiva vira
ordem SUGERIDA; o perfil de Manutenção só aceita ou descarta (Manutenção e admin).

"Aceita" é um carimbo interno: não cria ordem no Protheus nem escreve no outbox.
Toda a regra está em ``mes/services/maintenance_suggestions.py``; aqui só há
transporte, permissão e auditoria.
"""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request
from fastapi import Path as ApiPath

from backend.api.database import get_database
from backend.api.dependencies.auth import require_csrf, require_manutencao_user
from backend.api.dependencies.clock import request_now_func
from backend.api.errors import AppError
from backend.api.schemas.auth import SessionUser
from backend.api.schemas.maintenance import MaintenanceDecisionRequest
from mes.services.change_audit import auditar
from mes.services.maintenance_suggestions import (
    LIMITE_LISTA,
    MaintenanceSuggestionError,
    MaintenanceSuggestionService,
)

router = APIRouter(prefix="/maintenance", tags=["Manutenção"])

SuggestionId = Annotated[int, ApiPath(ge=1, le=9_223_372_036_854_775_807)]


def _service(database, user: SessionUser, request: Request) -> MaintenanceSuggestionService:
    return MaintenanceSuggestionService(
        database, user.id, user.name, now_func=request_now_func(request)
    )


def _executar(acao):
    """Converte erro de regra em ``AppError`` (409/404/422) com ``code``/``message``."""

    try:
        return acao()
    except MaintenanceSuggestionError as error:
        raise AppError(
            error.code, error.message, status_code=error.status_code, details=error.details
        ) from error


@router.get("/suggestions")
def list_suggestions(
    request: Request,
    status: Literal["sugerida", "aceita", "descartada"] = Query("sugerida"),
    user: SessionUser = Depends(require_manutencao_user),
    database=Depends(get_database),
):
    """Gera (lazy, idempotente) as sugestões das paradas dos últimos 7 dias e lista
    as do ``status`` pedido, mais recentes primeiro (até 200)."""

    items = _executar(lambda: _service(database, user, request).listar(status))
    return {"status": status, "limit": LIMITE_LISTA, "count": len(items), "items": items}


def _decidir(request, user, database, sugestao_id, payload, *, aceitar):
    service = _service(database, user, request)
    nota = payload.nota if payload else None
    item = _executar(
        lambda: service.aceitar(sugestao_id, nota) if aceitar else service.descartar(sugestao_id, nota)
    )
    auditar(
        database,
        user,
        "manutencao_sugestao",
        item["id"],
        antes={"status": "sugerida"},
        depois={
            "sugestao_id": item["id"],
            "recurso": item["recurso"],
            "parada_inicio": item["parada_inicio"],
            "status": item["status"],
            "nota": item["nota"],
        },
    )
    return {"ok": True, "item": item}


@router.post("/suggestions/{suggestion_id}/accept", dependencies=[Depends(require_csrf)])
def accept_suggestion(
    suggestion_id: SuggestionId,
    request: Request,
    payload: MaintenanceDecisionRequest | None = None,
    user: SessionUser = Depends(require_manutencao_user),
    database=Depends(get_database),
):
    """Aceita a sugestão (carimbo interno). 409 se já foi decidida, 404 se não existe."""

    return _decidir(request, user, database, suggestion_id, payload, aceitar=True)


@router.post("/suggestions/{suggestion_id}/discard", dependencies=[Depends(require_csrf)])
def discard_suggestion(
    suggestion_id: SuggestionId,
    request: Request,
    payload: MaintenanceDecisionRequest | None = None,
    user: SessionUser = Depends(require_manutencao_user),
    database=Depends(get_database),
):
    """Descarta a sugestão. 409 se já foi decidida, 404 se não existe."""

    return _decidir(request, user, database, suggestion_id, payload, aceitar=False)
