"""Casos de uso Web do posto do operador, sem regra produtiva na UI."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import FileResponse

from app.core.operator_sectors import WELDING_OPEN_PICKER_SECTORS, WELDING_SECTOR_NAMES
from backend.api.database import get_database
from backend.api.dependencies.auth import require_csrf, require_operator_user
from backend.api.dependencies.clock import request_now_func
from backend.api.dependencies.operator import sector_for_user, validate_resource
from backend.api.errors import AppError
from backend.api.schemas.auth import SessionUser
from backend.api.schemas.operator import FirstPieceRequest, OperatorActionRequest
from mes.domain.first_piece import sector_has_setup
from mes.services.drawings import DrawingLookupService, parse_drawing_roots
from mes.services.first_piece import FirstPieceService
from mes.services.operator_flow import OperatorFlowService
from mes.services.order_provisioning import STATUS_INDISPONIVEL, OrderProvisioningService


router = APIRouter(prefix="/operator", tags=["Operador"])


def _service(database, user: SessionUser, request: Request | None = None):
    return OperatorFlowService(
        database,
        user.name,
        now_func=request_now_func(request) if request is not None else None,
    )


def _operation(service, op: str, sector: str, resource: str, operation_id, operation_number):
    rows = service.listar_operacoes(op, sector, resource)
    selected = next(
        (
            row
            for row in rows
            if (
                operation_id is not None
                and (row.get("id") or row.get("catalogo_operacao_id")) == operation_id
            )
            or (
                operation_id is None
                and operation_number
                and str(row.get("numero_operacao") or row.get("codigo") or "").strip()
                == str(operation_number).strip()
            )
        ),
        None,
    )
    if selected is None:
        raise AppError(
            "operator_operation_unavailable",
            "A operação selecionada não pertence ao roteiro atual da OP.",
            status_code=409,
        )
    # A etapa fora da atual continua chegando ao domínio: quem decide entre
    # liberar, exigir a confirmação canônica de exceção ou bloquear é o
    # OperatorFlowService. O transporte só barra o que o posto nunca executa.
    if not selected.get("selectable"):
        current = next((row for row in rows if row.get("visual_current")), None)
        current_name = str(
            (current or {}).get("descricao_operacao")
            or (current or {}).get("nome")
            or (current or {}).get("numero_operacao")
            or "não identificada"
        ).strip()
        raise AppError(
            "operator_operation_not_actionable",
            f"Etapa atual: {current_name}. Esta operação não está disponível para {sector} neste posto.",
            status_code=409,
            details={
                "current_operation": current_name,
                "visual_status": selected.get("visual_status"),
            },
        )
    return selected


def _raise_result(result):
    if not result.ok:
        raise AppError(
            result.code or "operator_action_failed",
            result.message,
            status_code=409,
            details=result.data,
        )
    return {"ok": True, "message": result.message, "code": result.code, "data": result.data}


@router.get("/context")
def context(user: SessionUser = Depends(require_operator_user)):
    sector = sector_for_user(user)
    # Wave 6F — a estação é definida pelo login (não escolhida na tela) nos
    # setores da frente de Solda, exceto Proj. Ferramentaria e Protótipo: ali
    # uma conta só cobre vários recursos nomeados e o operador escolhe entre
    # eles, igual Dobra/Usinagem/Serra (decisão do usuário em 14/09/2026).
    welding = sector.name in WELDING_SECTOR_NAMES
    locked_to_login = welding and sector.name not in WELDING_OPEN_PICKER_SECTORS
    return {
        "sector": sector.name,
        "route": sector.route,
        "resources": list(sector.resources),
        "fixed_resource": locked_to_login and len(sector.resources) == 1,
        "station_profile_required": locked_to_login and len(sector.resources) != 1,
        # Quem decide se o posto tem Setup é o domínio, não a tela: o React
        # mantinha a própria lista de setores sem Setup e ela já nascia
        # desatualizada a cada setor novo.
        "has_setup": sector_has_setup(sector.name),
        "automatic_queue": sector.automatic_queue,
        "workflow": (
            "highlight" if sector.name == "Destaque"
            else "cutting" if sector.name == "Corte"
            else "workbench"
        ),
    }


@router.get("/stations")
def stations(
    user: SessionUser = Depends(require_operator_user),
    database=Depends(get_database),
):
    sector = sector_for_user(user)
    service = _service(database, user)
    items = []
    for resource in sector.resources:
        active = service.recurso_em_uso(sector.name, resource)
        owner = str((active or {}).get("operador_inicio") or (active or {}).get("operador_fila") or "").strip()
        status = "Livre"
        if active:
            status = "Selecionada" if owner.casefold() == user.name.casefold() else "Ocupada"
        items.append({"resource": resource, "status": status, "operator": owner or None})
    return {"sector": sector.name, "items": items}


def _provisioning(request: Request, database) -> OrderProvisioningService:
    """Fronteira neutra: a execução pede uma OP e não conhece a origem dela."""

    factory = getattr(request.app.state, "order_provisioning_factory", None)
    return factory(database) if callable(factory) else OrderProvisioningService()


@router.get("/operations/{op}")
def operations(
    request: Request,
    op: str,
    resource: str | None = Query(default=None, min_length=1, max_length=120),
    user: SessionUser = Depends(require_operator_user),
    database=Depends(get_database),
):
    """Consulta LOCAL do roteiro. Nunca aciona o planejamento corporativo.

    Quando a OP já existe, a resposta é imediata e o ERP não é consultado.
    Quando não existe, a resposta apenas sinaliza que uma busca remota é
    possível; quem decide pedir é o passo seguinte, explícito.
    """

    sector = sector_for_user(user)
    if sector.name in {"Destaque", "Corte"}:
        raise AppError("operator_workflow_mismatch", "Este setor utiliza um fluxo operacional próprio.", status_code=409)
    if resource is not None:
        _, resource = validate_resource(user, resource)
    rows = _service(database, user).listar_operacoes(op, sector.name, resource)
    # A consulta local não deve construir o adaptador corporativo quando a OP
    # já foi encontrada. O provisioning só participa do caminho de MISS.
    remote_available = False if rows else _provisioning(request, database).available
    return {
        "op": op,
        "sector": sector.name,
        "items": rows,
        "sync": {
            "source": "local" if rows else "miss",
            "pending": bool(not rows and remote_available),
            "remote_available": remote_available,
        },
    }


@router.post("/operations/{op}/sync", dependencies=[Depends(require_csrf)])
def provision_operation_order(
    request: Request,
    op: str,
    resource: str | None = Query(default=None, min_length=1, max_length=120),
    user: SessionUser = Depends(require_operator_user),
    database=Depends(get_database),
):
    """Provisiona a OP quando ela ainda não existe localmente.

    O operador não precisa abrir uma tela do ERP nem saber se a OP já foi
    sincronizada antes. Detalhe técnico (protocolo, traceback, código interno)
    nunca sai daqui: o operador recebe uma frase e o estado de negócio.
    """

    sector = sector_for_user(user)
    if sector.name in {"Destaque", "Corte"}:
        raise AppError("operator_workflow_mismatch", "Este setor utiliza um fluxo operacional próprio.", status_code=409)
    if resource is not None:
        _, resource = validate_resource(user, resource)
    provisioning = _provisioning(request, database)
    try:
        result = provisioning.provision(op)
    except Exception:
        logging.exception("Falha ao provisionar OP para o posto do operador.")
        raise AppError(
            "operator_order_provisioning_unavailable",
            provisioning.unavailable_message,
            status_code=503,
        ) from None
    if not result.found and result.status == STATUS_INDISPONIVEL:
        raise AppError(
            "operator_order_provisioning_unavailable",
            result.message,
            status_code=503,
        )

    items = (
        _service(database, user).listar_operacoes(result.op, sector.name, resource)
        if result.found
        else []
    )
    return {
        "op": result.op,
        "sector": sector.name,
        "items": items,
        "sync": {
            "status": result.status,
            "message": result.message,
            "found": result.found,
            "requested": result.requested,
            "idempotent": result.idempotent,
            "elapsed_seconds": round(result.elapsed_seconds, 3),
        },
    }


@router.get("/workbench")
def workbench(
    request: Request,
    resource: str = Query(min_length=1, max_length=120),
    user: SessionUser = Depends(require_operator_user),
    database=Depends(get_database),
):
    sector, resource = validate_resource(user, resource)
    if sector.automatic_queue:
        raise AppError("operator_workflow_mismatch", "Use a fila automática do Corte.", status_code=409)
    service = _service(database, user, request)
    cards = service.listar_cartoes(sector.name, resource)
    # O estado físico do recurso não cabe nos cards: uma parada registrada sem
    # OP não tem apontamento e, sem ele, a tela não teria como oferecer a
    # retomada. Mesmo contrato já usado pela fila do Corte.
    return {
        "sector": sector.name,
        "resource": resource,
        "resource_state": service.estado_recurso(resource),
        **cards,
    }


@router.get("/history")
def history(
    request: Request,
    resource: str = Query(min_length=1, max_length=120),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
    user: SessionUser = Depends(require_operator_user),
    database=Depends(get_database),
):
    sector, resource = validate_resource(user, resource)
    rows = _service(database, user, request).listar_historico(
        sector.name,
        resource,
        limite=page_size + 1,
        deslocamento=(page - 1) * page_size,
    )
    return {
        "sector": sector.name,
        "resource": resource,
        "items": rows[:page_size],
        "page": page,
        "page_size": page_size,
        "has_more": len(rows) > page_size,
    }


@router.get("/stop-reasons")
def stop_reasons(
    search: str | None = Query(default=None, max_length=120),
    user: SessionUser = Depends(require_operator_user),
    database=Depends(get_database),
):
    rows = _service(database, user).listar_motivos_parada()
    if search:
        needle = search.strip().casefold()
        rows = [
            row for row in rows
            if needle in str(row.get("codigo") or "").casefold()
            or needle in str(row.get("nome") or "").casefold()
        ]
    return {"items": rows}


@router.get("/operators")
def operators(
    user: SessionUser = Depends(require_operator_user),
    database=Depends(get_database),
):
    return {"items": _service(database, user).listar_operadores()}


# ---------------------------------------------------------------------------
# Primeira peça — o portão de liberação do lote (Wave 5)
#
# A inspeção é do próprio operador do posto: nenhum destes endpoints exige
# setor de Qualidade habilitado. A inspeção dimensional peça a peça continua
# existindo em `/quality`, para a operação INSPECAO do roteiro.
# ---------------------------------------------------------------------------
def _first_piece_service(database, user: SessionUser, request: Request | None = None):
    return FirstPieceService(
        database,
        user.name,
        now_func=request_now_func(request) if request is not None else None,
    )


def _first_piece_operation(service, op, sector, resource, operation_id, operation_number):
    """Localiza a etapa sem exigir que ela seja apontável neste instante.

    Uma OP bloqueada pelo retrabalho da primeira peça deixa de ser apontável —
    e é exatamente nela que o responsável precisa agir. Usar `_operation` aqui
    tornaria o desbloqueio impossível.
    """

    rows = service.listar_operacoes(op, sector, resource)
    selected = next(
        (
            row
            for row in rows
            if (
                operation_id is not None
                and (row.get("id") or row.get("catalogo_operacao_id")) == operation_id
            )
            or (
                operation_id is None
                and operation_number
                and str(row.get("numero_operacao") or row.get("codigo") or "").strip()
                == str(operation_number).strip()
            )
            or (operation_id is None and not operation_number and row.get("visual_current"))
        ),
        None,
    )
    if selected is None:
        raise AppError(
            "operator_operation_unavailable",
            "A operação selecionada não pertence ao roteiro atual da OP.",
            status_code=409,
        )
    return selected


@router.get("/first-piece")
def first_piece_state(
    request: Request,
    op: str = Query(min_length=1, max_length=80),
    resource: str = Query(min_length=1, max_length=120),
    operation_id: int | None = Query(default=None),
    operation_number: str | None = Query(default=None, max_length=40),
    user: SessionUser = Depends(require_operator_user),
    database=Depends(get_database),
):
    sector, resource = validate_resource(user, resource)
    flow = _service(database, user, request)
    operation = _first_piece_operation(
        flow, op, sector.name, resource, operation_id, operation_number
    )
    state = _first_piece_service(database, user, request).estado(
        op=op, setor=sector.name, recurso=resource, operacao=operation
    )
    return {
        "op": op,
        "sector": sector.name,
        "resource": resource,
        "operation_id": operation.get("id") or operation.get("catalogo_operacao_id"),
        "operation_number": operation.get("numero_operacao"),
        **state,
    }


@router.post("/first-piece", dependencies=[Depends(require_csrf)])
def first_piece_action(
    payload: FirstPieceRequest,
    request: Request,
    user: SessionUser = Depends(require_operator_user),
    database=Depends(get_database),
):
    sector, resource = validate_resource(user, payload.resource)
    if sector.name in {"Destaque", "Corte"}:
        raise AppError(
            "operator_workflow_mismatch",
            "Este setor utiliza um fluxo operacional próprio.",
            status_code=409,
        )
    flow = _service(database, user, request)
    operation = _first_piece_operation(
        flow, payload.op, sector.name, resource, payload.operation_id, payload.operation_number
    )
    service = _first_piece_service(database, user, request)
    if payload.action == "produzida":
        result = service.registrar_producao(
            op=payload.op, setor=sector.name, recurso=resource, operacao=operation
        )
    elif payload.action == "checklist":
        # Wave 6B — o popup Setup/Qualidade do Iniciar. A regra continua no
        # serviço: aqui só o transporte do formulário.
        result = service.registrar_checklist(
            op=payload.op,
            setor=sector.name,
            recurso=resource,
            operacao=operation,
            medidas=[item.model_dump() for item in payload.measures],
            destino=payload.destination,
            cracha_responsavel=payload.badge,
            observacao=payload.note,
        )
    elif payload.action == "inspecionar":
        if not payload.result:
            raise AppError(
                "primeira_peca_resultado_invalido",
                "Selecione Conforme, Retrabalho ou Refugo.",
                status_code=409,
            )
        result = service.inspecionar(
            op=payload.op,
            setor=sector.name,
            recurso=resource,
            operacao=operation,
            resultado=payload.result,
            observacao=payload.note,
        )
    else:
        result = service.autorizar(
            op=payload.op,
            setor=sector.name,
            recurso=resource,
            operacao=operation,
            cracha=payload.badge,
            observacao=payload.note,
        )
    if not result.ok:
        raise AppError(
            result.code or "primeira_peca_recusada",
            result.message,
            status_code=409,
            details=result.data,
        )
    request.app.state.realtime.publish("operator_first_piece")
    return {"ok": True, "message": result.message, "code": result.code, "data": result.data}


# ---------------------------------------------------------------------------
# Desenho da peça (PDF) — resolvido pelo backend, exibido dentro da aplicação
# ---------------------------------------------------------------------------
def _drawings(request: Request, database) -> DrawingLookupService:
    settings = request.app.state.settings
    return DrawingLookupService(
        database,
        roots=parse_drawing_roots(getattr(settings, "operator_drawing_roots", "")),
    )


@router.get("/drawings")
def drawing_metadata(
    request: Request,
    op: str = Query(min_length=1, max_length=80),
    user: SessionUser = Depends(require_operator_user),
    database=Depends(get_database),
):
    """Metadado do desenho. Nunca devolve caminho de rede para a tela."""

    return _drawings(request, database).buscar(op).como_dicionario()


@router.get("/drawings/file")
def drawing_file(
    request: Request,
    op: str = Query(min_length=1, max_length=80),
    user: SessionUser = Depends(require_operator_user),
    database=Depends(get_database),
):
    """Serve o PDF mais recente da peça, inline, para o visualizador embutido."""

    lookup = _drawings(request, database).buscar(op)
    if not lookup.available or lookup.path is None:
        raise AppError(
            "operator_drawing_unavailable",
            lookup.message or "Nenhum desenho disponível para esta OP.",
            status_code=404,
            details={"reason": lookup.reason},
        )
    return FileResponse(
        lookup.path,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="{lookup.selected.filename}"',
            "Cache-Control": "private, max-age=60",
        },
    )


@router.post("/actions", dependencies=[Depends(require_csrf)])
def execute_action(
    payload: OperatorActionRequest,
    request: Request,
    user: SessionUser = Depends(require_operator_user),
    database=Depends(get_database),
):
    sector, resource = validate_resource(user, payload.resource)
    if sector.name in {"Destaque", "Corte"}:
        raise AppError("operator_workflow_mismatch", "Este setor utiliza um fluxo operacional próprio.", status_code=409)
    service = _service(database, user, request)
    if payload.action == "Parada" and not payload.op:
        if not payload.stop_reason_code:
            raise AppError("operator_stop_reason_required", "Selecione o motivo da parada.")
        response = _raise_result(
            service.registrar_parada_recurso(
                setor=sector.name,
                recurso=resource,
                motivo_codigo=payload.stop_reason_code,
                comentario=payload.comment,
            )
        )
        request.app.state.realtime.publish("operator_stop_without_op")
        return response
    # Retomada simétrica: a parada sem OP é do recurso, não de um apontamento.
    # Sem este caminho o posto ficava travado em parada — não havia OP para
    # informar e toda ação caía em `operator_op_required`.
    if payload.action == "Retomar" and not payload.op:
        response = _raise_result(
            service.retomar_recurso_sem_op(setor=sector.name, recurso=resource)
        )
        request.app.state.realtime.publish("operator_action")
        return response
    if not payload.op:
        raise AppError(
            "operator_op_required",
            "Informe a OP e selecione uma operação antes de apontar.",
            status_code=409,
        )
    operation = _operation(
        service,
        payload.op,
        sector.name,
        resource,
        payload.operation_id,
        payload.operation_number,
    )
    result = service.executar(
        payload.action,
        op=payload.op,
        setor=sector.name,
        recurso=resource,
        operacao=operation,
        motivo_codigo=payload.stop_reason_code,
        comentario=payload.comment,
        pecas_boas=payload.good,
        refugo=payload.scrap,
        retrabalho_quantidade=payload.rework,
        lote=payload.lot,
        motivo_refugo=payload.scrap_reason,
        causa_raiz=payload.root_cause,
        tipo_setup=payload.setup_type,
        operadores_cracha=payload.badges,
        confirmar_recurso_divergente=payload.confirm_resource_divergence,
        confirmar_etapa_anterior_pendente=payload.confirm_previous_step,
        cracha_refugo=payload.scrap_authorization_badge,
        recurso_exclusivo=True,
    )
    response = _raise_result(result)
    request.app.state.realtime.publish("operator_action")
    return response
