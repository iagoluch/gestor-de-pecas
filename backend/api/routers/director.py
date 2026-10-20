"""Aba Diretoria (16/10/2026): Painel, Ficha e Custos em R$.

Única porta HTTP dos valores em R$: o router inteiro exige ``admin`` ou
``diretoria`` (``require_diretoria_user``). Regra de negócio fica em
``DirectorSummaryService``; aqui só se traduz erro de regra em ``AppError``.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query, Request
from fastapi import Path as ApiPath

from backend.api.database import get_database
from backend.api.dependencies.auth import require_csrf, require_diretoria_user
from backend.api.dependencies.bulkhead import management_read_slot
from backend.api.dependencies.clock import request_now_func
from backend.api.errors import AppError
from backend.api.schemas.auth import SessionUser
from backend.api.schemas.explanation import ValueExplanationResponse
from backend.api.schemas.director import (
    DirectorCostsResponse,
    DirectorPanelResponse,
    DirectorRateRequest,
    DirectorSheetResponse,
)
from mes.services.director_explanation import DirectorExplanationService
from mes.services.director_summary import DirectorSummaryError, DirectorSummaryService


router = APIRouter(
    prefix="/diretoria",
    tags=["Diretoria"],
    # Autorização antes do bulkhead: quem não pode ver não ocupa vaga de leitura.
    dependencies=[Depends(require_diretoria_user), Depends(management_read_slot)],
)


def _now(request: Request) -> datetime:
    # Mesmo relógio das demais rotas (``clock.now`` em simulação).
    now_func = request_now_func(request)
    return now_func() if now_func is not None else datetime.now()


def _app_error(error: DirectorSummaryError) -> AppError:
    return AppError(error.code, error.message, status_code=error.status_code, details=error.details)


@router.get("/painel", response_model=DirectorPanelResponse)
def panel(
    request: Request,
    periodo: str = Query(default="hoje", max_length=20),
    database=Depends(get_database),
):
    try:
        return DirectorSummaryService(database).panel(periodo, _now(request))
    except DirectorSummaryError as error:
        raise _app_error(error) from error


@router.get("/ficha", response_model=DirectorSheetResponse)
def sheet(
    request: Request,
    periodo: str = Query(default="hoje", max_length=20),
    setor: str | None = Query(default=None, max_length=60),
    recurso: str | None = Query(default=None, max_length=80),
    database=Depends(get_database),
):
    try:
        return DirectorSummaryService(database).sheet(periodo, setor, recurso, _now(request))
    except DirectorSummaryError as error:
        raise _app_error(error) from error


@router.get("/explicacao", response_model=ValueExplanationResponse)
def explain(
    request: Request,
    metric: str = Query(min_length=1, max_length=64),
    periodo: str = Query(default="hoje", max_length=20),
    setor: str | None = Query(default=None, max_length=60),
    recurso: str | None = Query(default=None, max_length=80),
    pessoa: str | None = Query(default=None, max_length=20),
    motivo: str | None = Query(default=None, max_length=80),
    database=Depends(get_database),
):
    """Conta aberta dos números em R$ e das horas da Diretoria (única porta dos valores em R$)."""
    try:
        return DirectorExplanationService(database).explain(
            metric.strip(), periodo, setor=setor, recurso=recurso, pessoa=pessoa, motivo=motivo, now=_now(request)
        ).to_dict()
    except DirectorSummaryError as error:
        raise _app_error(error) from error


@router.get("/custos", response_model=DirectorCostsResponse)
def costs(database=Depends(get_database)):
    return DirectorSummaryService(database).costs()


@router.put("/custos/recurso/{recurso}", dependencies=[Depends(require_csrf)])
def set_resource_rate(
    payload: DirectorRateRequest,
    recurso: str = ApiPath(min_length=1, max_length=80),
    user: SessionUser = Depends(require_diretoria_user),
    database=Depends(get_database),
):
    try:
        DirectorSummaryService(database).set_resource_rate(recurso, payload.valor_hora, user.name)
    except DirectorSummaryError as error:
        raise _app_error(error) from error
    return {"ok": True}


@router.put("/custos/pessoa/{operador_id}", dependencies=[Depends(require_csrf)])
def set_operator_rate(
    payload: DirectorRateRequest,
    operador_id: int = ApiPath(ge=1),
    user: SessionUser = Depends(require_diretoria_user),
    database=Depends(get_database),
):
    try:
        DirectorSummaryService(database).set_operator_rate(operador_id, payload.valor_hora, user.name)
    except DirectorSummaryError as error:
        raise _app_error(error) from error
    return {"ok": True}
