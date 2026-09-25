from __future__ import annotations

import asyncio
import json
import logging
from collections import Counter

from fastapi import APIRouter, Depends, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import StreamingResponse

from backend.api.dependencies.auth import require_management_user
from backend.api.dependencies.facade import get_frontend_facade
from backend.api.dependencies.filters import PageParams, analytics_filter, pagination
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
    _user: SessionUser = Depends(require_management_user),
    facade=Depends(get_frontend_facade),
):
    refresh_seconds = interval or request.app.state.settings.stream_interval_seconds

    async def events():
        falhando = False
        while True:
            if await request.is_disconnected():
                break
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
            except asyncio.CancelledError:
                break
            except Exception:
                # Uma entrada por episódio de falha, não uma a cada intervalo.
                if not falhando:
                    LOGGER.exception("Falha ao montar snapshot do stream operacional")
                falhando = True
                yield "event: error\ndata: {\"code\":\"stream_unavailable\",\"message\":\"Atualização temporariamente indisponível.\"}\n\n"
            await asyncio.sleep(refresh_seconds)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )
