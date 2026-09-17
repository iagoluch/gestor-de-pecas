"""Fila e comandos de Corte, adaptando diretamente o serviço canônico."""

import logging

from fastapi import APIRouter, Depends, Query, Request

from backend.api.database import get_database
from backend.api.dependencies.auth import (
    require_csrf,
    require_management_user,
    require_operator_user,
)
from backend.api.dependencies.clock import request_now_func
from backend.api.dependencies.operator import validate_resource
from backend.api.errors import AppError
from backend.api.schemas.auth import SessionUser
from backend.api.schemas.operator import CuttingActionRequest
from mes.services.cut import CutService
from mes.services.telegram_cut import build_cut_plan_notifier


router = APIRouter(prefix="/cutting", tags=["Corte"])
LOGGER = logging.getLogger(__name__)


def _service(database, user, request=None):
    return CutService(
        database,
        user.name,
        now_func=request_now_func(request) if request is not None else None,
    )


def _require_cutting(user, resource):
    sector, value = validate_resource(user, resource)
    if sector.name != "Corte":
        raise AppError("cutting_access_denied", "O perfil não possui acesso ao Corte.", status_code=403)
    return value


def _result(result):
    if not result.ok:
        raise AppError(result.code or "cutting_action_failed", result.message, status_code=409, details=result.data)
    return {"ok": True, "message": result.message, "code": result.code, "data": result.data}


@router.get("/queue")
def queue(
    request: Request,
    resource: str = Query(min_length=1, max_length=120),
    search: str | None = Query(default=None, max_length=160),
    user: SessionUser = Depends(require_operator_user),
    database=Depends(get_database),
):
    resource = _require_cutting(user, resource)
    service = _service(database, user, request)
    rows = service.listar_fila(resource)
    if search:
        needle = search.strip().casefold()

        def matches(row):
            direct = (
                "codigo_tarefa",
                "plano_hash",
                "programa",
                "programa_atual",
                "material",
                "nome_chapa",
                "sequencia_nesting",
                "nesting_atual",
            )
            if any(needle in str(row.get(key) or "").casefold() for key in direct):
                return True
            return any(
                needle in str(nesting.get(key) or "").casefold()
                for nesting in (row.get("nestings") or [])
                for key in ("plano_hash", "sequencia", "programa", "status")
            )

        rows = [
            row for row in rows
            if matches(row)
        ]
    return {
        "resource": resource,
        "resource_state": service.estado_recurso(resource),
        "items": rows,
        "sync": _sync_state(request, database),
    }


def _sync_state(request: Request, database) -> dict:
    """Situação da sincronização do planejamento, para a tela do Corte.

    ``ultima_sincronizacao`` é o instante em que um ciclo do SigmaNEST
    terminou com sucesso — não o último refresh do React. Depois de reiniciar
    o processo, o valor persistido no catálogo assume, para a tela não voltar
    a dizer "nunca sincronizado" com fila cheia.
    """

    coordinator = getattr(request.app.state, "sigmanest_refresh", None)
    estado = coordinator.state.as_dict() if coordinator is not None else {
        "ultima_sincronizacao": None,
        "ultimo_erro": None,
        "ultimo_erro_em": None,
        "executando": False,
        "ciclos": 0,
        "ultimo_resultado": {},
    }
    leitor = getattr(database, "ultima_sincronizacao_sigmanest", None)
    persistida = None
    if callable(leitor):
        try:
            persistida = (leitor() or {}).get("ultima_sincronizacao")
        except Exception:  # pragma: no cover - catálogo indisponível
            persistida = None
    memoria = estado.get("ultima_sincronizacao")
    if persistida and (memoria is None or persistida > memoria):
        estado["ultima_sincronizacao"] = persistida
    resultado = estado.get("ultimo_resultado") or {}
    return {
        "ultima_sincronizacao": estado.get("ultima_sincronizacao"),
        "executando": estado.get("executando", False),
        "ciclos": estado.get("ciclos", 0),
        "erro": estado.get("ultimo_erro"),
        "erro_em": estado.get("ultimo_erro_em"),
        # Só o que a tela precisa; o diagnóstico completo fica no log e no
        # endpoint administrativo.
        "tarefas_novas": resultado.get("tarefas_novas", 0),
        "tarefas_atualizadas": resultado.get("tarefas_atualizadas", 0),
        "chapas_novas": resultado.get("nestings_novos", 0),
        "automatica": bool(request.app.state.settings.sigmanest_sync_enabled),
    }


@router.post("/sync", dependencies=[Depends(require_csrf)])
async def sync(
    request: Request,
    resource: str = Query(min_length=1, max_length=120),
    user: SessionUser = Depends(require_operator_user),
    database=Depends(get_database),
):
    """Botão **Atualizar** da tela de Corte.

    Dispara uma sincronização imediata pelo MESMO ``SigmaNestSyncService`` do
    ciclo automático. Se um ciclo já estiver rodando, esta chamada adere a ele
    em vez de abrir um segundo — nada de leitura duplicada no SigmaNEST nem de
    watermark corrompida. Falha de leitura **não** apaga a fila local.
    """

    _require_cutting(user, resource)
    coordinator = getattr(request.app.state, "sigmanest_refresh", None)
    if coordinator is None:
        raise AppError(
            "cutting_sync_unavailable",
            "A sincronização automática não está configurada neste ambiente.",
            status_code=503,
        )
    resultado = await coordinator.sincronizar(origem="manual")
    if resultado.get("ok"):
        request.app.state.realtime.publish("cutting_queue")
    return {
        "ok": resultado.get("ok", False),
        "message": resultado.get("mensagem"),
        "aderiu_a_ciclo_em_andamento": resultado.get(
            "aderiu_a_ciclo_em_andamento", False
        ),
        "sync": _sync_state(request, database),
    }


@router.get("/sync/diagnostico")
def sync_diagnostics(
    request: Request,
    user: SessionUser = Depends(require_management_user),
):
    """Diagnóstico técnico do último ciclo, fora da tela do operador."""

    del user
    coordinator = getattr(request.app.state, "sigmanest_refresh", None)
    if coordinator is None:
        return {"disponivel": False, "motivo": "sincronização não configurada"}
    return {"disponivel": True, **coordinator.state.as_dict()}


@router.get("/history")
def history(
    request: Request,
    resource: str = Query(min_length=1, max_length=120),
    search: str | None = Query(default=None, max_length=160),
    status: str = Query(default="Todos", max_length=40),
    user: SessionUser = Depends(require_operator_user),
    database=Depends(get_database),
):
    """Consulta do que já passou pela máquina, sem alterar a fila ativa."""

    resource = _require_cutting(user, resource)
    rows = _service(database, user, request).listar_consulta(
        maquina=resource, status=status, search=search
    )
    return {"resource": resource, "status": status, "items": rows}


@router.post("/actions", dependencies=[Depends(require_csrf)])
def action(
    payload: CuttingActionRequest,
    request: Request,
    user: SessionUser = Depends(require_operator_user),
    database=Depends(get_database),
):
    resource = _require_cutting(user, payload.resource)
    service = _service(database, user, request)
    if payload.action == "Início":
        if not payload.plan_hash:
            raise AppError("cutting_plan_required", "Selecione um plano para iniciar.")
        result = service.iniciar(payload.plan_hash, resource)
        telegram_event = "corte_iniciado"
    elif payload.action == "Parada":
        if not payload.stop_reason_code:
            raise AppError("cutting_stop_reason_required", "Selecione o motivo da parada.")
        result = service.parar(resource, motivo_codigo=payload.stop_reason_code, comentario=payload.comment)
        telegram_event = None
    elif payload.action == "Retomada":
        result = service.retomar(resource)
        telegram_event = None
    else:
        if payload.appointment_id is None:
            raise AppError("cutting_appointment_required", "Não foi possível identificar o nesting em processo.")
        result = service.finalizar(payload.appointment_id)
        telegram_event = (
            "corte_finalizado"
            if (result.data or {}).get("status") == "Finalizado"
            else "corte_nesting_concluido"
        )
    response = _result(result)
    if telegram_event:
        try:
            notifier = build_cut_plan_notifier(
                database, request.app.state.settings
            )
            if notifier is not None:
                notifier.notify(result.data or {}, event=telegram_event)
        except Exception:
            # O fato industrial já foi persistido; indisponibilidade do canal
            # nunca pode desfazer nem transformar o apontamento em erro.
            LOGGER.exception("Falha ao atualizar o apontamento de Corte no Telegram.")
    request.app.state.realtime.publish("cutting_action")
    return response
