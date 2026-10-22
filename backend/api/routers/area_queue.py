"""Fila manual por recurso: líderes e supervisores ordenam a fila da própria área."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request

from app.core.areas import AREAS, recursos_da_area
from backend.api.database import get_database
from backend.api.dependencies.auth import require_csrf, require_management_user
from backend.api.dependencies.clock import request_now_func
from backend.api.errors import AppError
from backend.api.schemas.area_queue import AddQueueRequest, ReorderQueueRequest
from backend.api.schemas.auth import SessionUser
from mes.services.manual_queue import ManualQueueError, ManualQueueService

router = APIRouter(prefix="/areas/{area_id}/queue", tags=["Fila manual"])

_TOPICO = "operator_queue"


def _service(database, user: SessionUser, request: Request) -> ManualQueueService:
    return ManualQueueService(database, user.name, now_func=request_now_func(request))


def _autorizar_area(user: SessionUser, area_id: str) -> None:
    if area_id not in AREAS:
        raise AppError("area_not_found", "Área não encontrada.", status_code=404)
    if area_id not in user.queue_areas:
        raise AppError(
            "area_access_denied", "Seu perfil não gerencia a fila desta área.", status_code=403
        )


def _recurso_da_area(user: SessionUser, area_id: str, resource: str) -> dict:
    _autorizar_area(user, area_id)
    alvo = resource.strip().casefold()
    recurso = next(
        (item for item in recursos_da_area(area_id) if item["resource"].casefold() == alvo),
        None,
    )
    if recurso is None:
        raise AppError(
            "area_resource_denied",
            "Este recurso não pertence à sua área ou não tem fila manual.",
            status_code=403,
        )
    return recurso


def _executar(acao):
    """Converte erro de regra em 409 (ou o status do erro) com ``code``/``message``."""

    try:
        return acao()
    except ManualQueueError as error:
        raise AppError(
            error.code, error.message, status_code=error.status_code, details=error.details
        ) from error


@router.get("/resources")
def listar_recursos(
    area_id: str,
    user: SessionUser = Depends(require_management_user),
):
    _autorizar_area(user, area_id)
    return {
        "items": [
            {"resource": item["resource"], "nome": item["nome"], "setor": item["setor"]}
            for item in recursos_da_area(area_id)
        ]
    }


@router.get("")
def listar_fila(
    area_id: str,
    request: Request,
    resource: str = Query(min_length=1, max_length=120),
    user: SessionUser = Depends(require_management_user),
    database=Depends(get_database),
):
    recurso = _recurso_da_area(user, area_id, resource)
    return _service(database, user, request).listar(recurso)


@router.post("", dependencies=[Depends(require_csrf)])
def adicionar(
    area_id: str,
    payload: AddQueueRequest,
    request: Request,
    user: SessionUser = Depends(require_management_user),
    database=Depends(get_database),
):
    recurso = _recurso_da_area(user, area_id, payload.resource)
    resultado = _executar(lambda: _service(database, user, request).adicionar(recurso, payload.op))
    request.app.state.realtime.publish(_TOPICO)
    return resultado


@router.put("", dependencies=[Depends(require_csrf)])
def reordenar(
    area_id: str,
    payload: ReorderQueueRequest,
    request: Request,
    user: SessionUser = Depends(require_management_user),
    database=Depends(get_database),
):
    recurso = _recurso_da_area(user, area_id, payload.resource)
    resultado = _executar(
        lambda: _service(database, user, request).reordenar(recurso, payload.operation_ids)
    )
    request.app.state.realtime.publish(_TOPICO)
    return resultado


@router.delete("/{entry_id}", dependencies=[Depends(require_csrf)])
def remover(
    area_id: str,
    entry_id: int,
    request: Request,
    resource: str = Query(min_length=1, max_length=120),
    user: SessionUser = Depends(require_management_user),
    database=Depends(get_database),
):
    recurso = _recurso_da_area(user, area_id, resource)
    resultado = _executar(lambda: _service(database, user, request).remover(recurso, entry_id))
    request.app.state.realtime.publish(_TOPICO)
    return resultado
