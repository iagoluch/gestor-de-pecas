import logging
import re
import unicodedata
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from fastapi import Path as ApiPath

from app.core.password_policy import password_policy_error
from app.core.permissions import USER_LEVELS, can_access_management_web, is_maintenance_only, is_sector_operator
from app.database.errors import PauseOrderConflictError
from app.database.telegram_link_codes import TELEGRAM_LINK_CODE_TTL_SECONDS
from backend.api.database import get_database
from backend.api.dependencies.bulkhead import management_read_slot
from backend.api.dependencies.clock import request_now_func
from backend.api.dependencies.auth import (
    require_admin_user,
    require_csrf,
    require_management_user,
    require_qualidade_user,
    require_tempo_padrao_user,
)
from backend.api.dependencies.facade import get_frontend_facade
from backend.api.dependencies.filters import analytics_filter, scoped_sector
from backend.api.errors import AppError
from backend.api.schemas.auth import SessionUser
from backend.api.schemas.change_audit import AuditResponse
from backend.api.schemas.common import (
    AutomaticPauseRequest,
    OperatorBadgeRequest,
    ProductiveCalendarRequest,
    ProductiveResourceCalendarRequest,
    ProductiveShiftRequest,
    ShiftParameterRequest,
    StandardTimeManualRequest,
    UserAccountRequest,
    UserLevelRequest,
)
from mes.contracts import AnalyticsFilter
from mes.integrations.notifications.telegram import deliver_telegram_message, telegram_outbound_allowed
from mes.services.change_audit import auditar, consultar, encontrar, ler_estado
from mes.services.internal_alerts import InternalAlertService
from mes.services.standard_time import (
    RECALCULATION_JOB,
    RecalculationJob,
    StandardTimeRuleError,
    StandardTimeService,
)


router = APIRouter(
    prefix="/management",
    tags=["Gestão"],
    dependencies=[Depends(management_read_slot)],
)


@router.get("/overview")
def overview(
    filters: AnalyticsFilter = Depends(analytics_filter),
    _user: SessionUser = Depends(require_management_user),
    facade=Depends(get_frontend_facade),
):
    return facade.inicio(filters)


@router.get("/overview/trend")
def overview_trend(
    filters: AnalyticsFilter = Depends(analytics_filter),
    _user: SessionUser = Depends(require_management_user),
    facade=Depends(get_frontend_facade),
):
    return facade.inicio_tendencia(filters)


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
def _pause_in_scope(user: SessionUser, tipo_setor) -> bool:
    """Líder/supervisor só mexe nas pausas do próprio setor: elas mudam o OEE dele."""

    if not user.sector_scope:
        return True
    return str(tipo_setor or "").strip().casefold() in {setor.casefold() for setor in user.sector_scope}


def _require_pause_scope(user: SessionUser, tipo_setor) -> None:
    if not _pause_in_scope(user, tipo_setor):
        raise AppError("pause_out_of_scope", "Essa pausa é de outro setor.", status_code=403)


@router.get("/pauses")
def list_pauses(
    user: SessionUser = Depends(require_management_user),
    database=Depends(get_database),
):
    rows = [
        row for row in database.listar_pausas_automaticas(somente_ativas=False) or []
        if _pause_in_scope(user, row.get("tipo_setor"))
    ]
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
    antes = ler_estado(database, "listar_pausas_automaticas", somente_ativas=False)
    _require_pause_scope(user, payload.tipo_setor)
    if payload.id is not None:
        atual = encontrar(antes, "id", payload.id)
        if atual:
            _require_pause_scope(user, atual.get("tipo_setor"))
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
    except PauseOrderConflictError as exc:
        raise AppError("pause_order_taken", str(exc), status_code=409) from exc
    except ValueError as exc:
        raise AppError("invalid_pause_window", str(exc)) from exc
    if row is None:
        raise AppError("pause_not_found", "Pausa não encontrada.", status_code=404)
    auditar(database, user, "pausa", row.get("id"), antes=encontrar(antes, "id", row.get("id")), depois=row)
    request.app.state.realtime.publish("automatic_pauses")
    return {"ok": True, "item": row}


@router.delete("/pauses/{pause_id}", dependencies=[Depends(require_csrf)])
def delete_pause(
    pause_id: int,
    request: Request,
    user: SessionUser = Depends(require_management_user),
    database=Depends(get_database),
):
    antes = encontrar(ler_estado(database, "listar_pausas_automaticas", somente_ativas=False), "id", pause_id)
    if antes:
        _require_pause_scope(user, antes.get("tipo_setor"))
    if not database.remover_pausa_automatica(pause_id):
        raise AppError("pause_not_found", "Pausa não encontrada.", status_code=404)
    auditar(database, user, "pausa", pause_id, antes=antes)
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
    user: SessionUser = Depends(require_admin_user),
    database=Depends(get_database),
):
    antes = ler_estado(database, "listar_parametros_turno", somente_ativos=False)
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
    auditar(database, user, "turno", row.get("id"), antes=encontrar(antes, "id", row.get("id")), depois=row)
    request.app.state.realtime.publish("shift_parameters")
    return {"ok": True, "item": row}


@router.delete("/shift-parameters/{parameter_id}", dependencies=[Depends(require_csrf)])
def delete_shift_parameter(
    parameter_id: int,
    request: Request,
    user: SessionUser = Depends(require_admin_user),
    database=Depends(get_database),
):
    antes = encontrar(ler_estado(database, "listar_parametros_turno", somente_ativos=False), "id", parameter_id)
    if not database.remover_parametro_turno(parameter_id):
        raise AppError(
            "shift_parameter_not_found", "Turno não encontrado.", status_code=404
        )
    auditar(database, user, "turno", parameter_id, antes=antes)
    request.app.state.realtime.publish("shift_parameters")
    return {"ok": True}


# ---------------------------------------------------------------------------
# Calendário produtivo por recurso. Os métodos de persistência já existiam,
# mas sem uma chamada administrativa o catálogo anunciado em capabilities
# permanecia sempre no fallback global.
# ---------------------------------------------------------------------------
@router.post("/productive-calendars", dependencies=[Depends(require_csrf)])
def save_productive_calendar(
    payload: ProductiveCalendarRequest,
    request: Request,
    _user: SessionUser = Depends(require_admin_user),
    database=Depends(get_database),
):
    row = database.salvar_calendario_produtivo(
        payload.codigo,
        payload.nome,
        timezone=payload.timezone,
        ativo=payload.ativo,
    )
    request.app.state.realtime.publish("productive_calendars")
    return {"ok": True, "item": row}


@router.post(
    "/productive-calendars/{calendario_codigo}/turns",
    dependencies=[Depends(require_csrf)],
)
def save_productive_shift(
    calendario_codigo: Annotated[str, ApiPath(max_length=60)],
    payload: ProductiveShiftRequest,
    request: Request,
    _user: SessionUser = Depends(require_admin_user),
    database=Depends(get_database),
):
    try:
        row = database.salvar_turno_produtivo(
            calendario_codigo,
            payload.nome,
            payload.dia_semana,
            payload.hora_inicio,
            payload.hora_fim,
            cruza_meia_noite=payload.cruza_meia_noite,
            minutos_intervalo=payload.minutos_intervalo,
            ativo=payload.ativo,
        )
    except ValueError as exc:
        raise AppError("invalid_productive_shift", str(exc)) from exc
    request.app.state.realtime.publish("productive_calendars")
    return {"ok": True, "item": row}


@router.post("/resource-calendars", dependencies=[Depends(require_csrf)])
def bind_productive_resource_calendar(
    payload: ProductiveResourceCalendarRequest,
    request: Request,
    _user: SessionUser = Depends(require_admin_user),
    database=Depends(get_database),
):
    row = database.vincular_calendario_recurso(
        payload.recurso_codigo,
        payload.calendario_codigo,
        capacidade_valor=payload.capacidade_valor,
        capacidade_unidade=payload.capacidade_unidade,
    )
    if row is None:
        raise AppError("resource_not_found", "Recurso não encontrado no catálogo.", status_code=404)
    request.app.state.realtime.publish("productive_calendars")
    return {"ok": True, "item": row}


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
    # O chat_id é dado pessoal de contato: a tela só precisa saber se há vínculo.
    rows = [
        {
            **{key: value for key, value in row.items() if key != "telegram_chat_id"},
            "telegram_vinculado": bool(row.get("telegram_chat_id")),
        }
        for row in database.listar_operadores_apontamento(somente_ativos=False) or []
    ]
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
    item = {key: value for key, value in (row or {}).items() if key != "telegram_chat_id"}
    item["telegram_vinculado"] = bool((row or {}).get("telegram_chat_id"))
    return {"ok": True, "item": item}


# Vínculo do bot do Telegram (auditoria de segurança 2026-10-01): o crachá
# sozinho não vincula mais. A gestão gera um código de uso único, entregue em
# mãos ao dono do crachá, e só a gestão desfaz o vínculo.
TELEGRAM_UNLINK_NOTICE = (
    "🔗 Este chat foi desvinculado do Gestor de Peças pela gestão. "
    "Para voltar a consultar a fábrica, peça um novo código de vínculo."
)


@router.post("/badges/{operator_id}/telegram-link-code", dependencies=[Depends(require_csrf)])
def create_telegram_link_code(
    operator_id: int,
    user: SessionUser = Depends(require_admin_user),
    database=Depends(get_database),
):
    result = database.gerar_codigo_vinculo_telegram(operator_id, criado_por=user.name)
    status = result.get("status")
    if status == "nao_encontrado":
        raise AppError("badge_not_found", "Crachá não encontrado ou inativo.", status_code=404)
    if status == "ja_vinculado":
        raise AppError(
            "telegram_already_linked",
            "Este crachá já está vinculado a um chat. Desvincule antes de gerar um novo código.",
            status_code=409,
        )
    return {
        "ok": True,
        "code": result["codigo"],
        "expires_at": result["expira_em"],
        "valid_minutes": TELEGRAM_LINK_CODE_TTL_SECONDS // 60,
        "operator": result["operador"],
    }


@router.delete("/badges/{operator_id}/telegram-link", dependencies=[Depends(require_csrf)])
def remove_telegram_link(
    operator_id: int,
    request: Request,
    _user: SessionUser = Depends(require_admin_user),
    database=Depends(get_database),
):
    result = database.desvincular_telegram_operador(operator_id)
    if result is None:
        raise AppError("badge_not_found", "Crachá não encontrado.", status_code=404)
    previous_chat = result.get("chat_anterior")
    notified = bool(previous_chat) and _notify_telegram_chat(request, previous_chat, TELEGRAM_UNLINK_NOTICE)
    request.app.state.realtime.publish("operator_badges")
    return {"ok": True, "was_linked": bool(previous_chat), "previous_chat_notified": notified}


def _notify_telegram_chat(request: Request, chat_id: str, text: str) -> bool:
    """Aviso best-effort: falha de entrega não desfaz a desvinculação."""

    settings = request.app.state.settings
    if not getattr(settings, "telegram_configured", False):
        return False
    # Mesmo predicado único de saída do resto do Telegram (interruptor geral).
    if not telegram_outbound_allowed(settings):
        return False
    try:
        return bool(deliver_telegram_message(
            bot_token=settings.telegram_bot_token, chat_id=chat_id, text=text,
        ))
    except Exception:
        logging.getLogger(__name__).exception("Falha ao avisar o chat desvinculado no Telegram.")
        return False


# ---------------------------------------------------------------------------
# Alertas internos com notificação pendente.
#
# Este endpoint não envia nada e não é o `/management/alerts` da auditoria: ele
# lista os fatos industriais que precisam chegar a alguém (PCP, supervisão,
# responsável) e que a integração futura vai entregar.
# ---------------------------------------------------------------------------
@router.get("/internal-alerts")
def internal_alerts(
    recipient: str | None = Query(default=None, max_length=120),
    alert_type: str | None = Query(default=None, max_length=120),
    op: str | None = Query(default=None, max_length=80),
    pending_only: bool = False,
    user: SessionUser = Depends(require_management_user),
    database=Depends(get_database),
):
    service = InternalAlertService(database)
    items = service.listar(
        destinatario=recipient,
        tipo=alert_type,
        codigo_op=op,
        somente_pendentes=pending_only,
        setores=user.sector_scope,
    )
    return {
        "items": items,
        "count": len(items),
        "pending": sum(
            1 for row in items if str(row.get("status_notificacao")) == "PENDENTE"
        ),
        "summary": service.resumo(setores=user.sector_scope),
    }


# ---------------------------------------------------------------------------
# Cadastro de usuários — exclusivo da conta admin (decisão do usuário,
# 14/09/2026). A gestão comum continua sem poder criar login de ninguém, do
# mesmo jeito que não pode mais editar a lista de contatos de chamada.
# ---------------------------------------------------------------------------
#: Níveis "crus" (sem setor): decisão do usuário, 09/10/2026 — não se atribuem
#: mais a contas. Continuam existindo só como molde de permissões dos níveis por
#: setor (``nivel_base``) e para contas antigas que já os usam até serem trocadas.
UNASSIGNABLE_LEVELS = ("lider", "supervisor", "gestor")


def _tela_do_nivel(nivel, nivel_atribuido=None) -> str:
    """Onde a pessoa entra: gestão, apontamento, Manutenção ou outra (Andon/Almoxarifado)."""
    # O nível personalizado "manutencao" herda a base "lider" (gestão); a tela dela é só a de sugestões.
    if is_maintenance_only(nivel, nivel_atribuido):
        return "manutencao"
    if can_access_management_web(nivel):
        return "gestao"
    return "apontamento" if is_sector_operator(nivel) else "outro"


@router.get("/users")
def list_users(
    _user: SessionUser = Depends(require_admin_user),
    database=Depends(get_database),
):
    rows = [{**row, "tela": _tela_do_nivel(row.get("nivel"), row.get("nivel_atribuido"))} for row in database.listar_usuarios() or []]
    custom = list(database.listar_niveis_personalizados() or [])
    return {
        "items": rows,
        "count": len(rows),
        "active": sum(1 for row in rows if row.get("ativo")),
        "levels": [*USER_LEVELS, *(item["nome"] for item in custom)],
        "custom_levels": custom,
        "unassignable_levels": list(UNASSIGNABLE_LEVELS),
    }


def _slug_nivel(rotulo: str) -> str:
    texto = unicodedata.normalize("NFKD", rotulo).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "_", texto.lower()).strip("_")


@router.post("/levels", dependencies=[Depends(require_csrf)])
def create_level(
    payload: UserLevelRequest,
    user: SessionUser = Depends(require_admin_user),
    database=Depends(get_database),
):
    rotulo = payload.rotulo.strip()
    nome = _slug_nivel(rotulo)
    if not nome or payload.nivel_base not in USER_LEVELS or payload.nivel_base == "admin":
        raise AppError(
            "invalid_user_level",
            "Informe um nome para o nível e um nível-base válido.",
            status_code=422,
        )
    if nome in USER_LEVELS or nome == "comum" or not database.criar_nivel_personalizado(
        nome, rotulo, payload.nivel_base
    ):
        raise AppError(
            "level_name_taken",
            "Já existe um nível com esse nome.",
            status_code=409,
        )
    item = {"nome": nome, "rotulo": rotulo, "nivel_base": payload.nivel_base}
    auditar(database, user, "nivel", nome, depois=item)
    return {"ok": True, "item": item}


@router.delete("/levels/{nome}", dependencies=[Depends(require_csrf)])
def delete_level(
    # O slug nasce do rótulo (até 60 caracteres) e nunca fica mais longo (SEC-06).
    nome: Annotated[str, ApiPath(max_length=60)],
    user: SessionUser = Depends(require_admin_user),
    database=Depends(get_database),
):
    antes = encontrar(ler_estado(database, "listar_niveis_personalizados"), "nome", nome)
    if not database.excluir_nivel_personalizado(nome):
        existe = any(item["nome"] == nome for item in database.listar_niveis_personalizados() or [])
        if not existe:
            raise AppError("level_not_found", "Nível não encontrado.", status_code=404)
        raise AppError(
            "level_in_use",
            "Há contas usando este nível. Troque o nível delas antes de excluir.",
            status_code=409,
        )
    auditar(database, user, "nivel", nome, antes=antes)
    return {"ok": True}


@router.post("/users", dependencies=[Depends(require_csrf)])
def save_user(
    payload: UserAccountRequest,
    _user: SessionUser = Depends(require_admin_user),
    database=Depends(get_database),
):
    antes = None if payload.id is None else ler_estado(database, "obter_usuario_por_id", payload.id)
    custom_levels = list(database.listar_niveis_personalizados() or [])
    if payload.nivel not in USER_LEVELS and not any(
        item["nome"] == payload.nivel for item in custom_levels
    ):
        raise AppError(
            "invalid_user_level",
            "Nível de acesso inválido.",
            status_code=422,
        )
    if payload.nivel in UNASSIGNABLE_LEVELS:
        atual = next(
            (row.get("nivel_atribuido") for row in database.listar_usuarios() or [] if row["id"] == payload.id),
            None,
        )
        if atual != payload.nivel:
            raise AppError(
                "level_not_assignable",
                "Este nível não é mais atribuído. Escolha o nível do setor da pessoa.",
                status_code=422,
            )
    unidade = (payload.unidade or "").strip() or None
    if payload.senha:
        nivel_base = next(
            (item["nivel_base"] for item in custom_levels if item["nome"] == payload.nivel),
            payload.nivel,
        )
        erro_senha = password_policy_error(nivel_base, payload.senha)
        if erro_senha:
            raise AppError("user_password_weak", erro_senha, status_code=422)
    if payload.id is None:
        if not payload.senha:
            raise AppError(
                "user_password_required",
                "Defina uma senha para o novo usuário.",
                status_code=422,
            )
        usuario_id = database.criar_usuario(
            payload.nome, payload.senha, payload.nivel, ativo=payload.ativo, unidade=unidade
        )
        if usuario_id is None:
            raise AppError(
                "user_name_taken",
                "Já existe um usuário com esse nome.",
                status_code=409,
            )
    else:
        usuario_id = payload.id
        # Quem salva é sempre um admin ativo; barrar só a própria conta já
        # garante que o sistema nunca fica sem administrador pela tela.
        if usuario_id == _user.id and (not payload.ativo or payload.nivel != "admin"):
            raise AppError(
                "user_self_lockout",
                "Você não pode desativar nem rebaixar a própria conta. Peça a outro administrador.",
                status_code=409,
            )
        database.salvar_usuario(
            usuario_id,
            nivel=payload.nivel,
            ativo=payload.ativo,
            unidade=unidade,
            nova_senha=payload.senha or None,
        )
    row = database.obter_usuario_por_id(usuario_id)
    if row is None:
        raise AppError("user_not_found", "Usuário não encontrado.", status_code=404)
    # Só nome, nível, unidade e ativo seguem para o log (allowlist do Database):
    # a senha nunca é lida aqui e ``row`` não a traz.
    auditar(database, _user, "usuario", usuario_id, antes=antes, depois=row)
    return {"ok": True, "item": row}


@router.delete("/users/{usuario_id}", dependencies=[Depends(require_csrf)])
def delete_user(
    usuario_id: int,
    _user: SessionUser = Depends(require_admin_user),
    database=Depends(get_database),
):
    # Quem exclui é sempre um admin ativo; barrar a própria conta garante que
    # o sistema nunca fica sem administrador pela tela.
    if usuario_id == _user.id:
        raise AppError(
            "user_self_delete",
            "Você não pode excluir a própria conta. Peça a outro administrador.",
            status_code=409,
        )
    antes = ler_estado(database, "obter_usuario_por_id", usuario_id)
    if not database.excluir_usuario(usuario_id):
        raise AppError("user_not_found", "Usuário não encontrado.", status_code=404)
    auditar(database, _user, "usuario", usuario_id, antes=antes)
    return {"ok": True}


@router.get("/audit", response_model=AuditResponse)
def list_audit(
    entidade: str | None = Query(default=None, max_length=40),
    chave: str | None = Query(default=None, max_length=120),
    usuario: str | None = Query(default=None, max_length=80, description="Id ou parte do nome"),
    desde: date | None = None,
    ate: date | None = None,
    limite: int = Query(default=100, ge=1, le=500),
    _user: SessionUser = Depends(require_admin_user),
    database=Depends(get_database),
):
    """Quem mudou o quê (usuários, níveis, turnos, pausas), mais recente primeiro.

    Valores em R$ não passam por aqui: ficam em ``/diretoria/custos/auditoria``.
    """

    items = consultar(
        database, custos=False, entidade=entidade, chave=chave, usuario=usuario,
        desde=desde, ate=ate, limite=limite,
    )
    return {"items": items, "count": len(items)}


@router.get("/first-pieces")
def first_pieces(
    sector: str | None = Query(default=None, max_length=120),
    status: str | None = Query(default=None, max_length=120),
    blocked_only: bool = False,
    user: SessionUser = Depends(require_management_user),
    database=Depends(get_database),
):
    """Situação da primeira peça por operação, para a gestão e o relatório."""

    items = list(
        database.listar_primeiras_pecas(
            tipo_setor=scoped_sector(sector, user.sector_scope),
            status=status,
            somente_bloqueadas=blocked_only,
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


# ---------------------------------------------------------------------------
# Tempo padrão manual e estimado (06/10/2026).
#
# Exclusivo da engenharia de manufatura e do admin, inclusive a leitura: o
# gestor vê só o resultado (Performance) no payload gerencial. Prioridade da
# fonte: Protheus real > manual > estimado > NULL. O Corte não participa.
# ---------------------------------------------------------------------------
def _standard_time_error(error: StandardTimeRuleError) -> AppError:
    return AppError(error.code, error.message, status_code=error.status_code)


@router.get("/standard-times")
def list_standard_times(
    produto: str | None = Query(default=None, max_length=80),
    setor: str | None = Query(default=None, max_length=40),
    recurso: str | None = Query(default=None, max_length=80),
    somente_sem_padrao: bool = True,
    limit: int = 100,
    offset: int = 0,
    _user: SessionUser = Depends(require_tempo_padrao_user),
    database=Depends(get_database),
):
    result = database.listar_tempos_padrao(
        produto=produto or None,
        setor=setor or None,
        recurso=recurso or None,
        somente_sem_padrao=somente_sem_padrao,
        limite=max(1, min(int(limit), 500)),
        deslocamento=max(0, int(offset)),
    )
    return {
        "items": result["items"],
        "total": result["total"],
        "sem_produto": result.get("sem_produto", 0),
        "limit": max(1, min(int(limit), 500)),
        "offset": max(0, int(offset)),
        "somente_sem_padrao": somente_sem_padrao,
    }


@router.put("/standard-times/manual", dependencies=[Depends(require_csrf)])
def set_manual_standard_time(
    payload: StandardTimeManualRequest,
    user: SessionUser = Depends(require_tempo_padrao_user),
    database=Depends(get_database),
):
    service = StandardTimeService(database)
    try:
        saved = service.set_manual(
            payload.produto_codigo,
            payload.numero_operacao,
            payload.codigo_recurso,
            payload.segundos_por_peca,
            observacao=payload.observacao,
            usuario_id=user.id,
            usuario_nome=user.name,
        )
    except StandardTimeRuleError as error:
        raise _standard_time_error(error) from error
    return {"ok": True, "item": saved}


@router.delete("/standard-times/manual", dependencies=[Depends(require_csrf)])
def delete_manual_standard_time(
    produto_codigo: str = Query(max_length=80),
    numero_operacao: str = Query(max_length=40),
    codigo_recurso: str = Query(max_length=80),
    user: SessionUser = Depends(require_tempo_padrao_user),
    database=Depends(get_database),
):
    service = StandardTimeService(database)
    try:
        service.remove_manual(
            produto_codigo,
            numero_operacao,
            codigo_recurso,
            usuario_id=user.id,
            usuario_nome=user.name,
        )
    except StandardTimeRuleError as error:
        raise _standard_time_error(error) from error
    return {"ok": True}


@router.get("/standard-times/manual/history")
def manual_standard_time_history(
    produto_codigo: str = Query(max_length=80),
    numero_operacao: str = Query(max_length=40),
    codigo_recurso: str = Query(max_length=80),
    _user: SessionUser = Depends(require_tempo_padrao_user),
    database=Depends(get_database),
):
    items = database.listar_historico_tempo_padrao_manual(
        produto_codigo, numero_operacao, codigo_recurso
    )
    return {"items": items}


@router.post(
    "/standard-times/estimates/recalculate",
    status_code=202,
    dependencies=[Depends(require_csrf)],
)
def recalculate_standard_time_estimates(
    request: Request,
    _user: SessionUser = Depends(require_tempo_padrao_user),
    database=Depends(get_database),
):
    # Assíncrono: com volume alto o recálculo leva minutos. Responde 202 na hora
    # e o resultado sai em ``GET .../recalculate/status``. 409 se já houver um
    # em andamento (manual ou tick diário).
    # Mesmo relógio da aplicação do tick diário (``clock.now`` em simulação).
    service = StandardTimeService(database, now_func=request_now_func(request))
    try:
        started_at = RECALCULATION_JOB.start(service)
    except StandardTimeRuleError as error:
        raise _standard_time_error(error) from error
    return {"status": RecalculationJob.RUNNING, "started_at": started_at}


@router.get("/standard-times/estimates/recalculate/status")
def recalculate_standard_time_estimates_status(
    _user: SessionUser = Depends(require_tempo_padrao_user),
):
    return RECALCULATION_JOB.snapshot()


# ---------------------------------------------------------------------------
# Cotas padrão da Qualidade por produto (06/10/2026).
#
# Só a listagem vive aqui. A edição reutiliza POST /quality/templates e
# GET /quality/templates/{produto}, cuja guarda já aceita a conta ``qualidade``
# (QUALITY_TEMPLATE_EDITOR_LEVELS); não há rota de edição duplicada.
# ---------------------------------------------------------------------------
@router.get("/quality-templates")
def list_quality_templates(
    produto: str | None = Query(default=None, max_length=60),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    _user: SessionUser = Depends(require_qualidade_user),
    database=Depends(get_database),
):
    result = database.listar_templates_qualidade(
        produto=produto or None, limite=limit, deslocamento=offset
    )
    return {
        "items": result["items"],
        "total": result["total"],
        "limit": limit,
        "offset": offset,
    }
