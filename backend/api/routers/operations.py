from __future__ import annotations

import asyncio
import json
import logging
from collections import Counter

from fastapi import APIRouter, Depends, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import StreamingResponse

from backend.api.database import get_database
from backend.api.dependencies.auth import get_current_user, require_management_user
from backend.api.dependencies.facade import get_frontend_facade
from backend.api.dependencies.filters import PageParams, analytics_filter, pagination
from backend.api.errors import AppError
from backend.api.rate_limit import hold_while_streaming
from backend.api.schemas.auth import SessionUser
from mes.contracts import AnalyticsFilter


LOGGER = logging.getLogger(__name__)

router = APIRouter(prefix="/operations", tags=["Consulta operacional"])


def _page(items, params: PageParams):
    materialized = list(items or [])
    return {"items": params.slice(materialized), "page": params.meta(len(materialized))}


def _resource_summary(resources):
    """Consolida o que já veio do caso de uso, sem recalcular indicador.

    As telas gerenciais precisam responder "o que está acontecendo agora" com
    números, não com explicação de arquitetura. Aqui só se agrupa o estado
    físico que o backend canônico já resolveu.
    """

    rows = list(resources or [])
    categories = Counter(str(item.get("categoria") or "desconhecido") for item in rows)
    stopped = [
        item for item in rows
        if str(item.get("categoria") or "") == "parada"
        and item.get("duracao_segundos") is not None
    ]
    longest = max(stopped, key=lambda item: float(item.get("duracao_segundos") or 0.0), default=None)
    return {
        "resources": len(rows),
        "active_operations": sum(int(item.get("quantidade_ops_ativas") or 0) for item in rows),
        "by_category": dict(categories),
        "longest_stop": {
            "resource": longest.get("recurso"),
            "sector": longest.get("setor"),
            "reason": longest.get("motivo") or longest.get("codigo_status"),
            "seconds": float(longest.get("duracao_segundos") or 0.0),
        } if longest else None,
    }


@router.get("/overview")
def operations_overview(
    filters: AnalyticsFilter = Depends(analytics_filter),
    _user: SessionUser = Depends(require_management_user),
    facade=Depends(get_frontend_facade),
):
    payload = facade.consulta_operacional(
        filters,
        incluir_recursos_sem_demanda_de_contas=True,
        somente_recursos_em_uso=True,
    )
    resources = list(payload.get("resources", []))
    return {
        "periodo": payload.get("periodo"),
        "agora": payload.get("agora"),
        "resources": resources,
        "summary": _resource_summary(resources),
        "availability": "disponivel" if resources else "sem_registros",
    }


@router.get("/resources")
def resources(
    filters: AnalyticsFilter = Depends(analytics_filter),
    params: PageParams = Depends(pagination),
    _user: SessionUser = Depends(require_management_user),
    facade=Depends(get_frontend_facade),
):
    payload = facade.consulta_operacional(
        filters,
        incluir_recursos_sem_demanda_de_contas=True,
        somente_recursos_em_uso=True,
    )
    resources = list(payload.get("resources", []))
    return {
        "periodo": payload.get("periodo"),
        "agora": payload.get("agora"),
        "summary": _resource_summary(resources),
        **_page(resources, params),
    }


@router.get("/orders")
def active_orders(
    filters: AnalyticsFilter = Depends(analytics_filter),
    params: PageParams = Depends(pagination),
    _user: SessionUser = Depends(require_management_user),
    facade=Depends(get_frontend_facade),
):
    payload = facade.ordens_producao(filters)
    items = [
        item for item in payload.get("items", [])
        if str(item.get("status") or "").casefold() in {"aguardando", "em processo", "parada", "setup", "retrabalho"}
    ]
    return {"periodo": payload.get("periodo"), **_page(items, params)}


@router.get("/time")
def time_mes(
    filters: AnalyticsFilter = Depends(analytics_filter),
    _user: SessionUser = Depends(require_management_user),
    facade=Depends(get_frontend_facade),
):
    return facade.analise("tempos", filters)


@router.get("/stream")
async def stream(
    request: Request,
    filters: AnalyticsFilter = Depends(analytics_filter),
    interval: int | None = Query(default=None, ge=5, le=60),
    user: SessionUser = Depends(require_management_user),
    facade=Depends(get_frontend_facade),
    database=Depends(get_database),
):
    refresh_seconds = interval or request.app.state.settings.stream_interval_seconds
    lease = request.app.state.operations_stream_slots.try_acquire(user.id)
    if lease is None:
        raise AppError(
            "operations_stream_limit_reached",
            "Há telas demais acompanhando a operação ao vivo. Feche uma aba e tente de novo.",
            status_code=429,
        )

    def session_still_valid():
        # Mesma checagem da abertura (ativo, session_version, validade do
        # cookie, nível): conta desativada ou rebaixada perde o stream (SEC-01).
        require_management_user(get_current_user(request, database))

    async def events():
        # Cancelamento (cliente caiu, servidor desligando) não é capturado:
        # ``CancelledError`` não herda de ``Exception`` e sobe até
        # ``hold_while_streaming``, cujo ``finally`` devolve a vaga.
        falhando = False
        while True:
            if await request.is_disconnected():
                break
            try:
                await asyncio.to_thread(session_still_valid)
            except AppError as exc:
                data = json.dumps({"code": exc.code, "message": exc.message}, ensure_ascii=False)
                yield f"event: error\ndata: {data}\n\n"
                break
            except Exception:
                # Sem conseguir conferir a sessão (banco fora), nenhum dado
                # sai nesta volta: o stream espera e tenta de novo.
                if not falhando:
                    LOGGER.exception("Falha ao conferir a sessão do stream operacional")
                falhando = True
                yield "event: error\ndata: {\"code\":\"stream_unavailable\",\"message\":\"Atualização temporariamente indisponível.\"}\n\n"
                await asyncio.sleep(refresh_seconds)
                continue
            try:
                snapshot = await asyncio.to_thread(
                    facade.consulta_operacional,
                    filters,
                    incluir_recursos_sem_demanda_de_contas=True,
                    somente_recursos_em_uso=True,
                )
                data = json.dumps(jsonable_encoder(snapshot), ensure_ascii=False, separators=(",", ":"))
                falhando = False
                yield f"event: snapshot\ndata: {data}\n\n"
            except Exception:
                # Uma entrada por episódio de falha, não uma a cada intervalo.
                if not falhando:
                    LOGGER.exception("Falha ao montar snapshot do stream operacional")
                falhando = True
                yield "event: error\ndata: {\"code\":\"stream_unavailable\",\"message\":\"Atualização temporariamente indisponível.\"}\n\n"
            await asyncio.sleep(refresh_seconds)

    return StreamingResponse(
        hold_while_streaming(lease, events()),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )
