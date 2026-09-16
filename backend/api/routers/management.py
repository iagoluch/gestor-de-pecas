from fastapi import APIRouter, Depends, Request

from app.core.permissions import USER_LEVELS
from backend.api.database import get_database
from backend.api.dependencies.auth import (
    require_admin_user,
    require_csrf,
    require_management_user,
)
from backend.api.dependencies.facade import get_frontend_facade
from backend.api.dependencies.filters import analytics_filter
from backend.api.errors import AppError
from backend.api.schemas.auth import SessionUser
from backend.api.schemas.common import (
    AutomaticPauseRequest,
    OperatorBadgeRequest,
    ShiftParameterRequest,
    UserAccountRequest,
)
from mes.contracts import AnalyticsFilter
from mes.services.internal_alerts import InternalAlertService


router = APIRouter(
    prefix="/management",
    tags=["Gestão"],
)


@router.get("/overview")
def overview(
    filters: AnalyticsFilter = Depends(analytics_filter),
    _user: SessionUser = Depends(require_management_user),
    facade=Depends(get_frontend_facade),
):
    return facade.inicio(filters)


@router.get("/sectors")
def sectors(
    filters: AnalyticsFilter = Depends(analytics_filter),
    _user: SessionUser = Depends(require_management_user),
    facade=Depends(get_frontend_facade),
):
    payload = facade.inicio(filters)
    return {
        "periodo": payload.get("periodo"),
        "items": payload.get("sectors", []),
        "highlights": payload.get("sector_highlights", []),
        "count": len(payload.get("sectors", [])),
        "data_quality": payload.get("data_quality"),
    }


@router.get("/alerts")
def alerts(
    filters: AnalyticsFilter = Depends(analytics_filter),
    _user: SessionUser = Depends(require_management_user),
    facade=Depends(get_frontend_facade),
):
    audit = facade.auditoria(filters)
    return {
        "periodo": audit.get("periodo"),
        "items": audit.get("issues", []),
        "count": audit.get("count", 0),
        "by_severity": audit.get("by_severity", {}),
        "reliability_percentage": audit.get("reliability_percentage"),
        "reliability_reason": audit.get("reliability_reason"),
    }


@router.get("/insights")
def insights(
    filters: AnalyticsFilter = Depends(analytics_filter),
    _user: SessionUser = Depends(require_management_user),
    facade=Depends(get_frontend_facade),
):
    return facade.insights(filters)


@router.get("/kpis/{kpi_key}/explanation")
def kpi_explanation(
    kpi_key: str,
    filters: AnalyticsFilter = Depends(analytics_filter),
    _user: SessionUser = Depends(require_management_user),
    facade=Depends(get_frontend_facade),
):
    try:
        return facade.explain_kpi(kpi_key, filters)
    except ValueError as exc:
        raise AppError(
            "unknown_management_kpi",
            "KPI gerencial não suportado.",
            status_code=404,
        ) from exc


# ---------------------------------------------------------------------------
# Pausas automáticas por setor.
#
# O documento oficial de fluxo define horários diferentes por setor e prevê
# mudança futura, com mais de uma pausa por dia. Antes da Wave 3 esses horários
# viviam fixos no domínio; agora são configuração gerencial e o serviço de
# turno os lê a cada ciclo.
# ---------------------------------------------------------------------------
@router.get("/pauses")
def list_pauses(
    _user: SessionUser = Depends(require_management_user),
    database=Depends(get_database),
):
    rows = list(database.listar_pausas_automaticas(somente_ativas=False) or [])
    setores = sorted({str(row.get("tipo_setor") or "").strip() for row in rows if row.get("tipo_setor")})
    return {
        "items": rows,
        "sectors": setores,
        "count": len(rows),
        "active": sum(1 for row in rows if row.get("ativo")),
    }


@router.post("/pauses", dependencies=[Depends(require_csrf)])
def save_pause(
    payload: AutomaticPauseRequest,
    request: Request,
    user: SessionUser = Depends(require_management_user),
    database=Depends(get_database),
):
    try:
        row = database.salvar_pausa_automatica(
            tipo_setor=payload.tipo_setor,
            nome=payload.nome,
            hora_inicio=payload.hora_inicio,
            hora_fim=payload.hora_fim,
            ativo=payload.ativo,
            ordem=payload.ordem,
            pausa_id=payload.id,
            operador=user.name,
        )
    except ValueError as exc:
        raise AppError("invalid_pause_window", str(exc)) from exc
    if row is None:
        raise AppError("pause_not_found", "Pausa não encontrada.", status_code=404)
    request.app.state.realtime.publish("automatic_pauses")
    return {"ok": True, "item": row}


@router.delete("/pauses/{pause_id}", dependencies=[Depends(require_csrf)])
def delete_pause(
    pause_id: int,
    request: Request,
    _user: SessionUser = Depends(require_management_user),
    database=Depends(get_database),
):
    if not database.remover_pausa_automatica(pause_id):
        raise AppError("pause_not_found", "Pausa não encontrada.", status_code=404)
    request.app.state.realtime.publish("automatic_pauses")
    return {"ok": True}


# ---------------------------------------------------------------------------
# Turnos automáticos (H1/expediente/H2 e futuros) — tela IagoDev.
#
# Até esta tela, os horários de fim de turno e a janela oficial eram
# constantes fixas em código (`mes/domain/manufacturing_rules.py`). Exclusivo
# da conta admin (decisão do usuário, 15/09/2026): mudar esse horário afeta a
# fábrica inteira, não é uma preferência de gestão comum.
# ---------------------------------------------------------------------------
@router.get("/shift-parameters")
def list_shift_parameters(
    _user: SessionUser = Depends(require_admin_user),
    database=Depends(get_database),
):
    rows = list(database.listar_parametros_turno(somente_ativos=False) or [])
    return {"items": rows, "count": len(rows)}


@router.post("/shift-parameters", dependencies=[Depends(require_csrf)])
def save_shift_parameter(
    payload: ShiftParameterRequest,
    request: Request,
    _user: SessionUser = Depends(require_admin_user),
    database=Depends(get_database),
):
    try:
        row = database.salvar_parametro_turno(
            nome=payload.nome,
            tipo=payload.tipo,
            hora_inicio=payload.hora_inicio,
            hora_fim=payload.hora_fim,
            ativo=payload.ativo,
            ordem=payload.ordem,
            parametro_id=payload.id,
        )
    except ValueError as exc:
        raise AppError("invalid_shift_parameter", str(exc)) from exc
    if row is None:
        raise AppError("shift_parameter_not_found", "Turno não encontrado.", status_code=404)
    request.app.state.realtime.publish("shift_parameters")
    return {"ok": True, "item": row}


@router.delete("/shift-parameters/{parameter_id}", dependencies=[Depends(require_csrf)])
def delete_shift_parameter(
    parameter_id: int,
    request: Request,
    _user: SessionUser = Depends(require_admin_user),
    database=Depends(get_database),
):
    if not database.remover_parametro_turno(parameter_id):
        raise AppError(
            "shift_parameter_not_found", "Turno não encontrado.", status_code=404
        )
    request.app.state.realtime.publish("shift_parameters")
    return {"ok": True}


# ---------------------------------------------------------------------------
# Crachás do chão de fábrica e responsáveis autorizados (Wave 5).
#
# Até a Wave 4, "crachá autorizado" significava apenas "crachá ativo": qualquer
# pessoa cadastrada liberava qualquer exceção. A gestão passou a exigir um
# responsável designado para o retrabalho da primeira peça, e a designação vive
# no mesmo cadastro de crachás — sem login, sem perfil novo, sem autenticação
# paralela.
# ---------------------------------------------------------------------------
@router.get("/badges")
def list_badges(
    # Exclusivo do admin (decisão do usuário, 15/09/2026) — mesmo cadastro
    # que só a conta admin gerencia, como usuários e contatos de chamada.
    _user: SessionUser = Depends(require_admin_user),
    database=Depends(get_database),
):
    rows = list(database.listar_operadores_apontamento(somente_ativos=False) or [])
    autorizados = [row for row in rows if row.get("autorizador_retrabalho") and row.get("ativo")]
    return {
        "items": rows,
        "count": len(rows),
        "active": sum(1 for row in rows if row.get("ativo")),
        "authorizers": autorizados,
        "authorizer_count": len(autorizados),
    }


@router.post("/badges", dependencies=[Depends(require_csrf)])
def save_badge(
    payload: OperatorBadgeRequest,
    request: Request,
    _user: SessionUser = Depends(require_admin_user),
    database=Depends(get_database),
):
    try:
        row = database.cadastrar_operador_apontamento(
            payload.cracha,
            payload.nome,
            ativo=payload.ativo,
            fonte="gestao",
            autorizador_retrabalho=payload.autorizador_retrabalho,
        )
    except ValueError as exc:
        raise AppError("invalid_badge", str(exc)) from exc
    request.app.state.realtime.publish("operator_badges")
    return {"ok": True, "item": row}


# ---------------------------------------------------------------------------
# Alertas internos com notificação pendente.
#
# Este endpoint não envia nada e não é o `/management/alerts` da auditoria: ele
# lista os fatos industriais que precisam chegar a alguém (PCP, supervisão,
# responsável) e que a integração futura vai entregar.
# ---------------------------------------------------------------------------
@router.get("/internal-alerts")
def internal_alerts(
    recipient: str | None = None,
    alert_type: str | None = None,
    op: str | None = None,
    pending_only: bool = False,
    _user: SessionUser = Depends(require_management_user),
    database=Depends(get_database),
):
    service = InternalAlertService(database)
    items = service.listar(
        destinatario=recipient,
        tipo=alert_type,
        codigo_op=op,
        somente_pendentes=pending_only,
    )
    return {
        "items": items,
        "count": len(items),
        "pending": sum(
            1 for row in items if str(row.get("status_notificacao")) == "PENDENTE"
        ),
        "summary": service.resumo(),
    }


# ---------------------------------------------------------------------------
# Cadastro de usuários — exclusivo da conta admin (decisão do usuário,
# 14/09/2026). A gestão comum continua sem poder criar login de ninguém, do
# mesmo jeito que não pode mais editar a lista de contatos de chamada.
# ---------------------------------------------------------------------------
@router.get("/users")
def list_users(
    _user: SessionUser = Depends(require_admin_user),
    database=Depends(get_database),
):
    rows = list(database.listar_usuarios() or [])
    return {
        "items": rows,
        "count": len(rows),
        "active": sum(1 for row in rows if row.get("ativo")),
        "levels": list(USER_LEVELS),
    }


@router.post("/users", dependencies=[Depends(require_csrf)])
def save_user(
    payload: UserAccountRequest,
    _user: SessionUser = Depends(require_admin_user),
    database=Depends(get_database),
):
    if payload.nivel not in USER_LEVELS:
        raise AppError(
            "invalid_user_level",
            "Nível de acesso inválido.",
            status_code=422,
        )
    if payload.id is None:
        if not payload.senha:
            raise AppError(
                "user_password_required",
                "Defina uma senha para o novo usuário.",
                status_code=422,
            )
        usuario_id = database.criar_usuario(payload.nome, payload.senha, payload.nivel)
        if usuario_id is None:
            raise AppError(
                "user_name_taken",
                "Já existe um usuário com esse nome.",
                status_code=409,
            )
        if not payload.ativo:
            database.ativar_desativar_usuario(usuario_id, False)
    else:
        usuario_id = payload.id
        database.atualizar_nivel_usuario(usuario_id, payload.nivel)
        database.ativar_desativar_usuario(usuario_id, payload.ativo)
        if payload.senha:
            database.resetar_senha_usuario(usuario_id, payload.senha)
    row = database.obter_usuario_por_id(usuario_id)
    if row is None:
        raise AppError("user_not_found", "Usuário não encontrado.", status_code=404)
    return {"ok": True, "item": row}


@router.get("/first-pieces")
def first_pieces(
    sector: str | None = None,
    status: str | None = None,
    blocked_only: bool = False,
    _user: SessionUser = Depends(require_management_user),
    database=Depends(get_database),
):
    """Situação da primeira peça por operação, para a gestão e o relatório."""

    items = list(
        database.listar_primeiras_pecas(
            tipo_setor=sector, status=status, somente_bloqueadas=blocked_only
        )
        or []
    )
    return {
        "items": items,
        "count": len(items),
        "blocked": sum(1 for row in items if row.get("bloqueio_ativo")),
        "summary": list(database.resumo_primeira_peca() or []),
        "authorizations": list(
            database.listar_autorizacoes_primeira_peca(limite=200) or []
        ),
    }
