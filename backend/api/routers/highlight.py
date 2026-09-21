"""Fluxo operacional de Destaque por tarefa."""

from fastapi import APIRouter, BackgroundTasks, Depends, Request

from backend.api.database import get_database
from backend.api.dependencies.auth import require_csrf, require_operator_user
from backend.api.dependencies.clock import request_now_func
from backend.api.dependencies.operator import sector_for_user
from backend.api.errors import AppError
from backend.api.schemas.auth import SessionUser
from backend.api.schemas.operator import HighlightActionRequest
from mes.services.cut import CutService
from mes.services.production import ProductionService
from mes.services.operator_flow import OperatorFlowService
from mes.services.task_lookup import TarefaLookupService
from mes.services.telegram_alerts import schedule_resource_stop_alert


router = APIRouter(prefix="/highlight", tags=["Destaque"])


def _require_highlight(user):
    sector = sector_for_user(user)
    if sector.name != "Destaque":
        raise AppError("highlight_access_denied", "O perfil não possui acesso ao Destaque.", status_code=403)
    return sector


def _cutting_queue(database, operador, codigo_tarefa):
    """Situação de corte da tarefa, reaproveitando o serviço canônico de Corte.

    O Destaque só lê: nada aqui inicia, finaliza ou altera nesting.
    """

    codigo = str(codigo_tarefa or "").strip()
    if not codigo:
        return []
    try:
        linhas = CutService(database, operador).listar_consulta(search=codigo)
    except Exception:  # pragma: no cover - fila indisponível não bloqueia o Destaque
        return []
    return [
        {
            "codigo_tarefa": linha.get("codigo_tarefa"),
            "programa": linha.get("programa"),
            "maquina": linha.get("maquina"),
            "status": linha.get("status"),
            "nesting_count": linha.get("nesting_count"),
            "nestings_concluidos": linha.get("nestings_concluidos"),
            "nestings_em_processo": linha.get("nestings_em_processo"),
            "nestings_aguardando": linha.get("nestings_aguardando"),
            "data_inicio": linha.get("data_inicio"),
            "data_fim": linha.get("data_fim"),
            "nestings": linha.get("nestings") or [],
            # Mesma hierarquia da tela de Corte (tarefa -> plano -> OP ->
            # produto), já consolidada pelo read model canônico.
            "planos": linha.get("planos") or [],
            "ops_relacionadas": linha.get("ops_relacionadas") or [],
        }
        for linha in linhas
        if str(linha.get("codigo_tarefa") or "").strip().upper() == codigo.upper()
    ]


def _task_payload(database, service, task_code, *, operador=None):
    lookup = TarefaLookupService(database, operador).buscar_local(task_code)
    task = lookup.tarefa if lookup.ok else None
    if not task:
        raise AppError("highlight_task_not_found", "Tarefa não encontrada.", status_code=404)
    ops = list(database.listar_ops_por_tarefa(task["id"]) or [])
    historico = getattr(database, "listar_eventos_destaque", None)
    fila = getattr(database, "listar_fila_destaque", None)
    grupo = None
    if callable(fila):
        grupo = next(
            (
                item for item in (fila(limite=10000) or [])
                if int(item.get("tarefa_id") or 0) == int(task["id"])
            ),
            None,
        )
    # A tela operacional recebe somente chapas realmente liberadas pelo Corte.
    # O grupo completo continua sendo usado no backend para progresso e para
    # decidir quando a tarefa inteira terminou; plano aguardando Corte não é
    # opção de trabalho do operador do Destaque.
    planos_liberados = [
        plano for plano in (grupo or {}).get("planos", [])
        if plano.get("status_corte") == "Finalizado"
    ]
    return {
        "task": task,
        "operations": ops,
        # Planos da tarefa com situação de Corte e de Destaque, já consolidados
        # pelo backend. É isto que substitui a antiga "Fila de Ordem".
        "plans": planos_liberados,
        "progress": {
            "situacao": (grupo or {}).get("situacao"),
            "chapas_total": (grupo or {}).get("chapas_total"),
            "chapas_cortadas": (grupo or {}).get("chapas_cortadas"),
            "chapas_destacadas": (grupo or {}).get("chapas_destacadas"),
            "chapas_disponiveis": (grupo or {}).get("chapas_disponiveis"),
            "progresso_corte": (grupo or {}).get("progresso_corte"),
        },
        "state": service.estado_destaque(task["id"]),
        "timing": service.tempos_destaque(task["id"]),
        # Fila de Corte da própria tarefa: o operador enxerga o que já foi
        # cortado sem sair da tela do Destaque.
        "cutting": _cutting_queue(database, operador or "Destaque", task["codigo_tarefa"]),
        # Histórico do Destaque desta tarefa, direto dos eventos canônicos.
        "history": list(historico(task["id"]) or []) if callable(historico) else [],
    }


@router.get("/queue")
def queue(
    user: SessionUser = Depends(require_operator_user),
    database=Depends(get_database),
):
    """O que o Destaque pode processar agora, organizado por tarefa.

    Não é uma "Fila de Ordem" numerada de máquina: é o conjunto de tarefas
    cujo Corte já concluiu ao menos uma chapa. Cada plano aparece **dentro**
    da sua tarefa, nunca solto, e a contagem de chapas vem do SigmaNEST.
    """

    sector = _require_highlight(user)
    itens = [
        item for item in (database.listar_fila_destaque(limite=10000) or [])
        if int(item.get("chapas_disponiveis") or 0) > 0
        and str(item.get("status_tarefa") or "") not in {"Finalizado", "Despachado"}
    ][:60]
    return {
        "items": itens,
        "count": len(itens),
        # A parada registrada sem tarefa é do posto, não da tarefa: sem o
        # estado físico aqui a tela não teria como oferecer a retomada — a
        # consulta de tarefa nem é feita quando nenhuma está carregada.
        "resource_state": OperatorFlowService(database, user.name).estado_recurso(sector.name),
        "parciais": sum(1 for item in itens if item.get("situacao") == "PARCIAL"),
        "completas": sum(1 for item in itens if item.get("situacao") == "COMPLETA"),
        "planos_disponiveis": sum(
            int(item.get("chapas_disponiveis") or 0) for item in itens
        ),
    }


@router.get("/tasks/{task_code}")
def task(
    task_code: str,
    request: Request,
    user: SessionUser = Depends(require_operator_user),
    database=Depends(get_database),
):
    _require_highlight(user)
    return _task_payload(
        database,
        ProductionService(database, user.name, now_func=request_now_func(request)),
        task_code,
        operador=user.name,
    )


@router.post("/actions", dependencies=[Depends(require_csrf)])
def action(
    payload: HighlightActionRequest,
    request: Request,
    background: BackgroundTasks,
    user: SessionUser = Depends(require_operator_user),
    database=Depends(get_database),
):
    sector = _require_highlight(user)
    service = ProductionService(database, user.name, now_func=request_now_func(request))
    if payload.action == "Parada" and not payload.stop_reason_code:
        raise AppError("highlight_stop_reason_required", "Selecione o motivo da parada.")
    # Retomada simétrica da parada sem tarefa: ela é do posto, e exigir uma
    # tarefa aqui deixava o Destaque parado para sempre. A tarefa parada
    # continua sendo retomada pelo Início, que é a transição do destaque.
    if payload.action == "Retomar":
        if payload.task_code:
            raise AppError(
                "highlight_resume_task_scoped",
                "Esta tarefa é retomada pelo Início do destaque.",
                status_code=409,
            )
        result = OperatorFlowService(
            database, user.name, now_func=request_now_func(request)
        ).retomar_recurso_sem_op(setor=sector.name, recurso=sector.name)
        if not result.ok:
            raise AppError(result.code or "highlight_action_failed", result.message, status_code=409, details=result.data)
        request.app.state.realtime.publish("highlight_action")
        return {"ok": True, "message": result.message, "code": result.code, "data": result.data}
    if not payload.task_code and payload.action != "Parada":
        raise AppError("highlight_task_required", "Busque uma tarefa antes de continuar.", status_code=409)

    current = (
        _task_payload(database, service, payload.task_code, operador=user.name)
        if payload.task_code
        else None
    )
    task_row = current["task"] if current else None
    if payload.action == "Início":
        result = service.registrar_destacando(
            task_row["id"], task_row["codigo_tarefa"], plano_hash=payload.plan_hash
        )
    elif payload.action == "Parada":
        plano_em_execucao = next(
            (
                plano for plano in (current or {}).get("plans", [])
                if str(plano.get("plano_hash") or "") == str(payload.plan_hash or "")
                and plano.get("estado_destaque") in {"inicio", "retomada"}
            ),
            None,
        )
        if current and (plano_em_execucao or current["state"].get("estado") in {"inicio", "retomada"}):
            result = service.registrar_parada_destaque(
                task_row["id"],
                task_row["codigo_tarefa"],
                motivo_codigo=payload.stop_reason_code,
                comentario=payload.comment,
                plano_hash=payload.plan_hash,
            )
        else:
            result = OperatorFlowService(
                database, user.name, now_func=request_now_func(request)
            ).registrar_parada_recurso(
                setor="Destaque",
                recurso="Destaque",
                motivo_codigo=payload.stop_reason_code,
                comentario=payload.comment,
            )
    else:
        badge = str(payload.badge or "").strip()
        finder = getattr(database, "buscar_operadores_apontamento", None)
        operators = list(finder([badge]) or []) if badge and callable(finder) else []
        if not operators:
            raise AppError("highlight_badge_invalid", "Informe um crachá cadastrado e ativo.", status_code=409)
        operator_name = str(operators[0].get("nome") or badge).strip()
        result = service.registrar_finalizado(
            task_row["id"], task_row["codigo_tarefa"],
            operador_identificacao=operator_name,
            plano_hash=payload.plan_hash,
        )
    if not result.ok:
        raise AppError(result.code or "highlight_action_failed", result.message, status_code=409, details=result.data)
    if payload.action == "Parada":
        # O Destaque é um posto único: a linha devolvida identifica a tarefa,
        # o nome do posto vem do próprio setor.
        parada = dict(result.data or {})
        parada.setdefault("maquina", "Destaque")
        parada.setdefault("setor", "Destaque")
        if payload.task_code:
            parada.setdefault("codigo_tarefa", payload.task_code)
        schedule_resource_stop_alert(background, request.app.state.settings, parada)
    request.app.state.realtime.publish("highlight_action")
    response = {
        "ok": True,
        "message": result.message,
        "code": result.code,
        "data": result.data,
    }
    if task_row:
        response["current"] = _task_payload(
            database, service, task_row["codigo_tarefa"], operador=user.name
        )
    return response
