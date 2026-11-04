"""Consulta de OP: dados da OP, roteiro completo e histórico do roteiro.

Leitura para a gestão; a etapa adicionada (PCP, engenharia de manufatura e
admin) é a única escrita e NÃO vai ao Protheus. Regra em
``mes/services/order_route.py``; aqui só transporte, permissão e erros.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from fastapi import Path as ApiPath
from pydantic import BaseModel, ConfigDict, Field

from backend.api.database import get_database
from backend.api.dependencies.auth import require_csrf, require_management_user
from backend.api.dependencies.clock import request_now_func
from backend.api.errors import AppError
from backend.api.schemas.auth import SessionUser
from mes.services.order_provisioning import OrderProvisioningService
from mes.services.order_route import OrderRouteService, RouteStepError

router = APIRouter(prefix="/order-consultation", tags=["Produção"])

StepId = Annotated[int, ApiPath(ge=1, le=9_223_372_036_854_775_807)]


class AddStepRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    after_operation_id: int | None = Field(default=None, ge=1)
    description: str = Field(max_length=200)
    resource_code: str = Field(max_length=100)
    reason: str = Field(max_length=1000)


class DeactivateStepRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(max_length=1000)


def _service(database, user: SessionUser, request: Request) -> OrderRouteService:
    return OrderRouteService(
        database, user.id, user.name, user.role, user.assigned_level,
        now_func=request_now_func(request),
    )


def _executar(acao):
    try:
        return acao()
    except RouteStepError as error:
        raise AppError(error.code, error.message, status_code=error.status_code) from error


@router.get("/search")
def search_orders(
    request: Request,
    q: str = Query("", max_length=60),
    user: SessionUser = Depends(require_management_user),
    database=Depends(get_database),
):
    """OPs que casam (código, produto ou descrição); até 20. Mínimo de 2 caracteres."""

    items = _service(database, user, request).buscar(q)
    return {"items": items, "count": len(items)}


def _provisioning(request: Request, database) -> OrderProvisioningService:
    factory = getattr(request.app.state, "order_provisioning_factory", None)
    return factory(database) if callable(factory) else OrderProvisioningService()


@router.post("/{codigo_op}/protheus", dependencies=[Depends(require_csrf)])
def check_in_protheus(
    codigo_op: Annotated[str, ApiPath(min_length=1, max_length=40)],
    request: Request,
    user: SessionUser = Depends(require_management_user),
    database=Depends(get_database),
):
    """Coleta a OP no Protheus (se faltar no Gestor) e informa se já passou pelo sistema."""

    state = request.app.state
    claims = getattr(request.state, "session_claims", None)
    sessao = getattr(claims, "session_id", None) or f"conta:{user.id}"
    if not state.op_sync_session_limiter.hit(sessao) or not state.op_sync_account_limiter.hit(user.id):
        raise AppError(
            "order_consultation_rate_limited",
            "Muitas consultas ao Protheus em pouco tempo. Aguarde um minuto e tente de novo.",
            status_code=429,
        )
    return _executar(
        lambda: _service(database, user, request).consultar_protheus(
            codigo_op, _provisioning(request, database)
        )
    )


@router.get("/{codigo_op}")
def consult_order(
    codigo_op: Annotated[str, ApiPath(min_length=1, max_length=40)],
    request: Request,
    user: SessionUser = Depends(require_management_user),
    database=Depends(get_database),
):
    """Dados da OP + roteiro completo + histórico de alterações do roteiro."""

    return _executar(lambda: _service(database, user, request).consultar(codigo_op))


@router.post("/{codigo_op}/steps", dependencies=[Depends(require_csrf)])
def add_step(
    codigo_op: Annotated[str, ApiPath(min_length=1, max_length=40)],
    payload: AddStepRequest,
    request: Request,
    user: SessionUser = Depends(require_management_user),
    database=Depends(get_database),
):
    """Inclui etapa apontável depois de uma operação. 403 sem permissão; não vai ao Protheus."""

    item = _executar(
        lambda: _service(database, user, request).adicionar_etapa(
            codigo_op, apos_operacao_id=payload.after_operation_id,
            descricao=payload.description, recurso=payload.resource_code,
            motivo=payload.reason,
        )
    )
    return {"ok": True, "item": item}


@router.post("/{codigo_op}/steps/{step_id}/deactivate", dependencies=[Depends(require_csrf)])
def deactivate_step(
    codigo_op: Annotated[str, ApiPath(min_length=1, max_length=40)],
    step_id: StepId,
    payload: DeactivateStepRequest,
    request: Request,
    user: SessionUser = Depends(require_management_user),
    database=Depends(get_database),
):
    """Desativa (não apaga) uma etapa adicionada no Gestor; etapa do Protheus é recusada."""

    item = _executar(
        lambda: _service(database, user, request).desativar_etapa(
            codigo_op, step_id, motivo=payload.reason
        )
    )
    return {"ok": True, "item": item}
