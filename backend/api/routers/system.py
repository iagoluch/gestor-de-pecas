from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict
from typing import Literal

from backend.api.dependencies.auth import (
    get_current_user,
    require_csrf,
    require_management_user,
)
from mes.services.frontend_facade import FrontendBackendFacade
from mes.services.corporate_integration import totvs_production_order_status


router = APIRouter(prefix="/system", tags=["Sistema"])


class SimulationClockRequest(BaseModel):
    """Pausa/retomada do relógio virtual, exclusiva do modo de simulação."""

    model_config = ConfigDict(extra="forbid")

    action: Literal["pause", "resume"]


def _simulation_clock_payload(settings, clock) -> dict:
    return {
        "enabled": settings.simulation_mode,
        "reference_time": (
            clock.now().isoformat()
            if clock is not None and settings.simulation_mode
            else None
        ),
        "time_scale": settings.simulation_time_scale,
        "running": bool(clock.running) if clock is not None else False,
        "paused": bool(clock.paused) if clock is not None else False,
    }


@router.get("/capabilities")
def capabilities(request: Request):
    payload = FrontendBackendFacade(None).capabilities()
    payload["api"] = {
        "version": "v1",
        "authentication": "postgresql_user_http_only_cookie",
        "realtime": "sse",
        "operator_web_enabled": True,
        "management_web_enabled": True,
    }
    settings = request.app.state.settings
    clock = getattr(request.app.state, "clock", None)
    simulation_now = clock.now() if clock is not None and settings.simulation_mode else None
    payload["simulation"] = {
        "enabled": settings.simulation_mode,
        "reference_time": (
            simulation_now.isoformat()
            if simulation_now is not None
            else None
        ),
        "time_scale": settings.simulation_time_scale,
        "running": bool(clock.running) if clock is not None else False,
        "paused": bool(clock.paused) if clock is not None else False,
    }
    corporate = totvs_production_order_status(settings)
    payload["corporate_integration"] = {
        "provider": corporate.provider,
        "configured": corporate.configured,
        "planning_read_enabled": corporate.planning_read_enabled,
        "execution_write_enabled": corporate.execution_write_enabled,
        "reason": corporate.reason,
    }
    payload["active_data_source"] = "postgresql_test_only"
    return payload


@router.post(
    "/simulation/clock",
    dependencies=[Depends(require_csrf)],
)
def simulation_clock(
    payload: SimulationClockRequest,
    request: Request,
    _user=Depends(require_management_user),
):
    """Congela ou retoma o relógio virtual sem tocar no tempo real."""

    settings = request.app.state.settings
    clock = getattr(request.app.state, "clock", None)
    if not settings.simulation_mode or clock is None:
        raise HTTPException(
            status_code=409,
            detail={
                "error": {
                    "code": "simulacao_desabilitada",
                    "message": "O relógio virtual só pode ser controlado no modo de simulação.",
                }
            },
        )
    changed = clock.pause() if payload.action == "pause" else clock.resume()
    result = _simulation_clock_payload(settings, clock)
    result["changed"] = changed
    return result


@router.get("/health")
def health(request: Request):
    payload = request.app.state.database_manager.health()
    payload["api"] = "available"
    return JSONResponse(
        status_code=200 if payload["status"] == "ok" else 503,
        content=payload,
    )


@router.get("/events")
async def events(request: Request, _user=Depends(get_current_user)):
    """Canal SSE autenticado usado somente para invalidar consultas abertas."""

    return StreamingResponse(
        request.app.state.realtime.stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
