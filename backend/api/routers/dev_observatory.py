"""Dev Observatory — rota separada, exclusiva do desenvolvedor.

Fora da navegação dos operadores e da área gerencial: a página vive em
``/dev-observatory`` e os dados em ``/api/v1/dev-observatory``. O login é
próprio da ferramenta — uma única credencial configurada por variável de
ambiente (``GESTOR_DEVOBS_LOGIN_USERNAME``/``GESTOR_DEVOBS_LOGIN_PASSWORD``),
com sessão assinada por um segredo separado (``GESTOR_DEVOBS_SESSION_SECRET``).
Não usa a tabela ``usuarios`` nem a sessão principal do Gestor de Peças, de
propósito: as duas devem poder mudar, quebrar ou girar sem afetar uma a outra
(ver ``backend/api/dependencies/auth.py::require_dev_observatory_user``).

Sobre o ambiente REAL: **somente leitura**, garantida pelo PostgreSQL e
verificada na abertura da conexão (``backend/observability/readonly_db.py``).
Os dados observados continuam somente leitura — inclusive no REAL — e nada
aqui fala com TOTVS ou SigmaNEST. O login grava apenas o contador técnico do
freio de autenticação na tabela compartilhada de throttling.
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime
from pathlib import Path
import html
import hmac
import json
import logging
import secrets
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, Response
from pydantic import BaseModel, ConfigDict, Field

from backend.api.dependencies.auth import (
    DEV_OBSERVATORY_ROLE,
    decode_dev_observatory_claims,
    require_dev_observatory_user,
)
from backend.api.dependencies.filters import unscoped_analytics_filter
from backend.ai.provider_profiles import PROFILES_BY_HOST
from backend.api.database import get_database
from backend.api.errors import AppError
from backend.api.schemas.auth import SessionUser
from backend.api.security.login_throttle import login_throttle_key
from backend.integrations.totvs_soap import _arrived_through_public_host
from backend.observability import metrics as metrics_module
from backend.observability.shift_report import (
    build_report,
    current_window,
    find_window,
    list_reports,
    report_exists,
    shift_windows_for_date,
    write_report,
)
from backend.observability import quick_fixes
from mes.contracts import AnalyticsFilter
from mes.contracts.ai import AIProviderError
from mes.services.frontend_facade import FrontendBackendFacade

LOGGER = logging.getLogger(__name__)


def _reject_if_public_host(request: Request) -> None:
    """Ferramenta de desenvolvedor: nunca deve responder pelo túnel público.

    Mesmo com login próprio (``require_dev_observatory_user``), esse login usa
    credencial e segredo de sessão separados do principal — uma segunda linha
    de defesa mais fraca por design. Bloquear no hostname publicado (mesmo
    contrato de ``backend/integrations/totvs_soap.py``) impede que a superfície
    fique exposta na internet mesmo se aquela credencial for adivinhada.
    """

    if _arrived_through_public_host(request):
        raise AppError(
            "dev_observatory_internal_only",
            "O Dev Observatory responde somente na rede interna.",
            status_code=403,
        )


router = APIRouter(
    prefix="/dev-observatory",
    tags=["Dev Observatory"],
    dependencies=[Depends(_reject_if_public_host)],
)
page_router = APIRouter(
    prefix="/dev-observatory",
    include_in_schema=False,
    dependencies=[Depends(_reject_if_public_host)],
)

PAGE_DIR = Path(__file__).resolve().parents[2] / "observability" / "page"

TEST_ENVIRONMENT = "test"
REAL_ENVIRONMENT = "real"


class ReportRequest(BaseModel):
    """Geração manual de um relatório de turno já encerrado (ou em curso)."""

    model_config = ConfigDict(extra="forbid")

    day: date | None = None
    shift: str = Field(default="turno", max_length=32)
    force: bool = False


class DiagnoseRequest(BaseModel):
    """Pede à IA a leitura de UMA evidência que o servidor já guarda."""

    model_config = ConfigDict(extra="forbid")

    sequence: int | None = Field(default=None, ge=1)
    report: str | None = Field(default=None, max_length=128)
    question: str | None = Field(default=None, max_length=500)


class ChatTurn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=4000)


class ChatRequest(BaseModel):
    """Conversa sem estado no servidor: o cliente reenvia as últimas falas."""

    model_config = ConfigDict(extra="forbid")

    messages: list[ChatTurn] = Field(min_length=1, max_length=40)
    sequences: list[int] = Field(default_factory=list, max_length=3)
    include_snapshot: bool = True


class TerminateBackendRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pid: int = Field(ge=1)


# ---------------------------------------------------------------------------
# Infraestrutura comum
# ---------------------------------------------------------------------------
def _recorder(request: Request):
    recorder = getattr(request.app.state, "dev_observatory", None)
    if recorder is None:
        raise AppError(
            "dev_observatory_disabled",
            "O Dev Observatory está desabilitado nesta instância (GESTOR_DEV_OBSERVATORY_ENABLED).",
            status_code=409,
        )
    return recorder


def _real_manager(request: Request):
    manager = getattr(request.app.state, "dev_observatory_real", None)
    if manager is None:
        raise AppError(
            "dev_observatory_disabled",
            "O Dev Observatory está desabilitado nesta instância.",
            status_code=409,
        )
    return manager


def _environment_database(request: Request, environment: str):
    """Devolve a facade de persistência do ambiente pedido.

    TESTE é o banco da própria API. REAL é um pool separado, somente leitura,
    que nunca compete com o pool que atende o operador.
    """

    if environment == TEST_ENVIRONMENT:
        return request.app.state.database_manager.get()
    if environment == REAL_ENVIRONMENT:
        try:
            return _real_manager(request).get()
        except AppError:
            raise
        except Exception as exc:
            raise AppError(
                "dev_observatory_real_unavailable",
                str(exc),
                status_code=503,
            ) from exc
    raise AppError(
        "dev_observatory_unknown_environment",
        "Ambiente inválido: use 'test' ou 'real'.",
        status_code=400,
    )


def _api_environment(application) -> dict:
    database = application.state.database_manager.get()
    target = dict(getattr(database, "safe_target", {}) or {})
    return {
        "name": TEST_ENVIRONMENT,
        "database": target.get("dbname"),
        "host": target.get("host"),
        "port": target.get("port"),
        "user": target.get("user"),
        "writable": True,
    }


# ---------------------------------------------------------------------------
# Login próprio — isolado da tabela `usuarios` e da sessão principal (ver
# backend/api/dependencies/auth.py::require_dev_observatory_user e
# backend/api/config.py). Comparação em tempo constante (`secrets.compare_digest`)
# contra a credencial única configurada por variável de ambiente.
# ---------------------------------------------------------------------------
class DevObservatoryLoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=256)


def _dev_observatory_cookie_options(request: Request) -> dict:
    settings = request.app.state.settings
    return {
        "secure": settings.cookie_secure,
        "samesite": "strict",
        "path": "/",
        "max_age": settings.dev_observatory_session_ttl_seconds,
    }


def _require_dev_observatory_csrf(request: Request) -> None:
    """Protege mutações usando o token da sessão exclusiva do observatório."""

    settings = request.app.state.settings
    token = request.cookies.get(settings.dev_observatory_cookie_name)
    if not token:
        raise AppError(
            "dev_observatory_authentication_required",
            "Entre no Dev Observatory para continuar.",
            status_code=401,
        )
    claims = decode_dev_observatory_claims(request, token)
    header = str(request.headers.get("X-CSRF-Token") or "")
    cookie = str(request.cookies.get(settings.dev_observatory_csrf_cookie_name) or "")
    if not header or not cookie or not hmac.compare_digest(header, claims.csrf) or not hmac.compare_digest(cookie, claims.csrf):
        raise AppError(
            "csrf_validation_failed",
            "A confirmação de segurança da sessão é obrigatória.",
            status_code=403,
        )


# Freio de adivinhação de senha. Atrás desta única credencial estão stack
# trace, catálogo do PostgreSQL e leitura do ambiente REAL — e o Gestor é
# publicado por hostname externo (``GESTOR_WEB_PUBLIC_HOST``). Sem freio, a
# senha fica exposta a tentativa ilimitada por quem alcançar a URL.
LOGIN_MAX_FAILURES = 5
LOGIN_LOCKOUT_SECONDS = 300


def _credential_matches(sent: str, configured: str) -> bool:
    """Comparação em tempo constante que aceita qualquer caractere.

    ``secrets.compare_digest`` levanta ``TypeError`` quando recebe ``str`` com
    caractere fora do ASCII — uma senha acentuada derrubava o endpoint com 500
    em vez de recusar com 401. Em bytes UTF-8 a comparação vale para qualquer
    senha e continua sem vazar tempo.
    """

    return secrets.compare_digest(sent.encode("utf-8"), configured.encode("utf-8"))


@router.post("/login")
def dev_observatory_login(
    payload: DevObservatoryLoginRequest,
    request: Request,
    database=Depends(get_database),
):
    settings = request.app.state.settings
    # Prefixo próprio: o mesmo IP+usuário no login principal não pode zerar
    # (sucesso) nem inflar (falha) o contador do observatório, e vice-versa.
    throttle_key = "devobs:" + login_throttle_key(request, payload.username)
    # Contador persistente em `login_throttle`, sem caminho em memória (BK-22).
    if int(
        database.obter_falhas_login(throttle_key, janela_segundos=LOGIN_LOCKOUT_SECONDS) or 0
    ) >= LOGIN_MAX_FAILURES:
        raise AppError(
            "dev_observatory_login_blocked",
            "Muitas tentativas seguidas. Aguarde alguns minutos para tentar de novo.",
            status_code=429,
        )
    configured_username = settings.dev_observatory_login_username
    configured_password = settings.dev_observatory_login_password
    # As duas comparações são feitas sempre: avaliar a senha só quando o usuário
    # confere transformaria o tempo de resposta em oráculo de usuário válido.
    username_ok = _credential_matches(payload.username, configured_username)
    password_ok = _credential_matches(payload.password, configured_password)
    valid = bool(configured_username) and bool(configured_password) and username_ok and password_ok
    if not valid:
        database.registrar_falha_login(throttle_key, janela_segundos=LOGIN_LOCKOUT_SECONDS)
        raise AppError(
            "dev_observatory_invalid_credentials",
            "Usuário ou senha inválidos.",
            status_code=401,
        )
    database.limpar_falhas_login(throttle_key)
    token, claims = request.app.state.dev_observatory_session_signer.issue(
        user_id=0, username=payload.username, role=DEV_OBSERVATORY_ROLE,
    )
    response = JSONResponse(content={"username": payload.username})
    response.set_cookie(
        settings.dev_observatory_cookie_name,
        token,
        httponly=True,
        **_dev_observatory_cookie_options(request),
    )
    response.set_cookie(
        settings.dev_observatory_csrf_cookie_name,
        claims.csrf,
        httponly=False,
        **_dev_observatory_cookie_options(request),
    )
    response.headers["Cache-Control"] = "no-store"
    return response


@router.post("/logout", status_code=204)
def dev_observatory_logout(request: Request):
    settings = request.app.state.settings
    response = Response(status_code=204)
    response.delete_cookie(
        settings.dev_observatory_cookie_name,
        path="/",
        secure=settings.cookie_secure,
        samesite="strict",
    )
    response.delete_cookie(
        settings.dev_observatory_csrf_cookie_name,
        path="/",
        secure=settings.cookie_secure,
        samesite="strict",
    )
    return response


# ---------------------------------------------------------------------------
# Dados
# ---------------------------------------------------------------------------
@router.get("/status")
def status(request: Request, _user: SessionUser = Depends(require_dev_observatory_user)):
    """Situação do observatório: ambientes, garantia de leitura e relógio."""

    recorder = _recorder(request)
    settings = request.app.state.settings
    clock = getattr(request.app.state, "clock", None)
    now = clock.now() if clock is not None else datetime.now()
    window = current_window(now)
    try:
        api_environment = _api_environment(request.app)
    except Exception as exc:
        api_environment = {"name": TEST_ENVIRONMENT, "database": None, "error": str(exc)}
    return {
        "generated_at": now.isoformat(timespec="seconds"),
        "environments": {
            "test": api_environment,
            "real": _real_manager(request).status(),
        },
        "simulation": {
            "enabled": settings.simulation_mode,
            "time_scale": settings.simulation_time_scale,
            "running": bool(getattr(clock, "running", False)),
        },
        "current_shift": window.as_dict() if window is not None else None,
        "summary": recorder.live_summary(),
        # Só o nome da pasta: o caminho absoluto do servidor não sai daqui (SEC-10).
        "report_dir": Path(settings.dev_observatory_report_dir).name,
        "ai": _ai_status(request),
        "quick_actions": {"terminate_backend": _terminate_allowed(settings)},
        "write_policy": {
            "database_writes": "nenhuma — o observatório persiste apenas em disco; "
                               "única ação sobre o banco: encerrar sessão travada, só no TESTE",
            "real_access": "somente leitura verificada contra o PostgreSQL",
            "external_integrations": "nenhuma — não envia nada a TOTVS/SigmaNEST",
        },
    }


@router.get("/events")
def events(
    request: Request,
    limit: int = Query(default=120, ge=1, le=600),
    classification: str | None = Query(default=None, max_length=200),
    _user: SessionUser = Depends(require_dev_observatory_user),
):
    """Eventos capturados: erros reais, bloqueios esperados e ações de escrita."""

    recorder = _recorder(request)
    items = recorder.recent_events(limit=limit, classification=classification)
    return {
        "items": items,
        "count": len(items),
        "summary": recorder.live_summary(),
        "traffic": recorder.recent_traffic(limit=80),
    }


@router.get("/viewports")
def viewports(
    request: Request,
    environment: str = Query(default=TEST_ENVIRONMENT, alias="env", pattern="^(test|real)$"),
    # Sem escopo de setor: o observatório tem sessão própria, não a do MES.
    filters: AnalyticsFilter = Depends(unscoped_analytics_filter),
    _user: SessionUser = Depends(require_dev_observatory_user),
):
    """Estado corrente somente dos postos com apontamento canônico real.

    Não existe projeção nova aqui: a fonte é a mesma
    ``FrontendBackendFacade.consulta_operacional``. Diferente da Consulta
    Operacional gerencial, não exibe inventário/capacidade sem OP, rota ou
    demanda local comprovada. Publica eventos/sessões/apontamentos de execução,
    incluindo ``apontamentos_corte`` para Laser e Plasma.
    """

    database = _environment_database(request, environment)
    settings = request.app.state.settings
    clock = getattr(request.app.state, "clock", None)
    simulation = bool(settings.simulation_mode) and environment == TEST_ENVIRONMENT
    facade = FrontendBackendFacade(
        database,
        now_func=clock.now if simulation and clock is not None else None,
        simulation_mode=simulation,
    )
    payload = facade.consulta_operacional(filters, somente_vinculo_operacional=True)
    target = dict(getattr(database, "safe_target", {}) or {})
    return {
        "environment": environment,
        "database": target.get("dbname"),
        "read_only": environment == REAL_ENVIRONMENT,
        "generated_at": payload.get("agora"),
        "periodo": payload.get("periodo"),
        "items": payload.get("resources", []),
        "count": payload.get("count", 0),
        "source": "FrontendBackendFacade.consulta_operacional(vinculo_operacional)",
    }


@router.get("/metrics")
def metrics(
    request: Request,
    environment: str = Query(default=TEST_ENVIRONMENT, alias="env", pattern="^(test|real)$"),
    _user: SessionUser = Depends(require_dev_observatory_user),
):
    """Latência da API, PostgreSQL do ambiente pedido e memória do processo."""

    recorder = _recorder(request)
    database = _environment_database(request, environment)
    postgres = metrics_module.collect_postgres_metrics(database)
    return {
        "environment": environment,
        "postgres": postgres,
        "process": metrics_module.process_metrics(),
        "api": recorder.live_summary(),
    }


@router.get("/shifts")
def shifts(
    request: Request,
    day: date | None = Query(default=None),
    _user: SessionUser = Depends(require_dev_observatory_user),
):
    """Janelas canônicas do dia e quais já possuem relatório gravado."""

    settings = request.app.state.settings
    clock = getattr(request.app.state, "clock", None)
    now = clock.now() if clock is not None else datetime.now()
    reference = day or now.date()
    report_dir = settings.dev_observatory_report_dir
    windows = []
    for window in shift_windows_for_date(reference):
        item = window.as_dict()
        item["closed"] = window.end <= now
        item["current"] = window.start <= now < window.end
        item["report"] = report_exists(report_dir, window)
        windows.append(item)
    return {
        "day": reference.isoformat(),
        "now": now.isoformat(timespec="seconds"),
        "windows": windows,
        "source": "mes.domain.manufacturing_rules (OFFICIAL_WORK_WINDOW + OVERTIME_WINDOWS)",
    }


@router.get("/reports")
def reports(request: Request, _user: SessionUser = Depends(require_dev_observatory_user)):
    settings = request.app.state.settings
    items = list_reports(settings.dev_observatory_report_dir)
    return {
        "items": items,
        "count": len(items),
        "directory": Path(settings.dev_observatory_report_dir).name,
    }


@router.get("/reports/{name}", response_class=PlainTextResponse)
def report_content(
    name: str,
    request: Request,
    _user: SessionUser = Depends(require_dev_observatory_user),
):
    return PlainTextResponse(
        _report_file(request, name).read_text(encoding="utf-8"),
        media_type="text/markdown; charset=utf-8",
    )


def _report_file(request: Request, name: str) -> Path:
    base = Path(request.app.state.settings.dev_observatory_report_dir).resolve()
    target = (base / name / "report.md").resolve()
    # Travessia de diretório é recusada explicitamente: o nome vem da URL.
    if base not in target.parents or not target.is_file():
        raise AppError("report_not_found", "Relatório não encontrado.", status_code=404)
    return target


# ---------------------------------------------------------------------------
# Ações rápidas (ver backend/observability/quick_fixes.py)
# ---------------------------------------------------------------------------
_AI_LOCK = asyncio.Lock()  # uma chamada por vez: o provedor tem cota e é compartilhado


class AIConfigRequest(BaseModel):
    """Chave e modelo da IA digitados na tela. A chave nunca volta nas respostas."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    provider: Literal["nvidia", "groq", "openrouter"]
    model: str = Field(min_length=1, max_length=200, pattern=r"^[\w./:@+-]+$")
    # Vazia = manter a chave já salva (só trocar o modelo).
    api_key: str = Field(default="", max_length=400)


PROFILES_BY_NAME = {profile.name: profile for profile in PROFILES_BY_HOST.values()}

# Sugestões para o seletor; o campo aceita qualquer id que o provedor ofereça.
AI_MODEL_SUGGESTIONS = {
    "nvidia": [
        "nvidia/nemotron-3-super-120b-a12b",
        "nvidia/nemotron-3-ultra",
        "z-ai/glm-5.3",
        "meta/llama-3.3-70b-instruct",
    ],
    "groq": ["openai/gpt-oss-120b", "openai/gpt-oss-20b", "llama-3.3-70b-versatile"],
    "openrouter": ["openai/gpt-oss-120b", "anthropic/claude-sonnet-4.5", "google/gemini-2.5-flash"],
}


def _ai_override_path(settings) -> Path:
    return Path(settings.dev_observatory_report_dir) / "ai_override.json"


def _build_ai_provider(settings, *, api_key: str, model: str, base_url: str):
    from backend.ai.openai_compatible_provider import OpenAICompatibleProvider

    return OpenAICompatibleProvider(
        api_key=api_key,
        model=model,
        base_url=base_url,
        reasoning_effort=settings.ai_reasoning_effort,
        temperature=settings.ai_temperature,
        max_completion_tokens=settings.ai_max_completion_tokens,
        request_token_budget=settings.ai_request_token_budget,
        timeout_seconds=settings.ai_timeout_seconds,
    )


def _load_ai_override(application) -> None:
    """Aplica uma vez a chave/modelo salvos pela tela (dev_reports/, fora do Git).

    Vale só para a IA do observatório (``devobs_ai_provider``): a IA Industrial
    da gestão (``ai_provider``) segue sempre o .env.
    """

    state = application.state
    if getattr(state, "devobs_ai_override_loaded", False):
        return
    state.devobs_ai_override_loaded = True
    path = _ai_override_path(state.settings)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        profile = PROFILES_BY_NAME[data["provider"]]
        state.devobs_ai_override = {
            "provider": profile.name,
            "model": str(data["model"]),
            "api_key": str(data["api_key"]),
        }
        state.devobs_ai_provider = _build_ai_provider(
            state.settings,
            api_key=state.devobs_ai_override["api_key"],
            model=state.devobs_ai_override["model"],
            base_url=profile.default_base_url,
        )
    except FileNotFoundError:
        pass
    except Exception:
        LOGGER.warning("ai_override.json inválido; ignorado", exc_info=True)


def _ai_provider(request: Request):
    _load_ai_override(request.app)
    state = request.app.state
    provider = getattr(state, "devobs_ai_provider", None)
    if provider is None:
        provider = getattr(state, "ai_provider", None)
        if not (state.settings.ai_enabled and state.settings.ai_configured):
            provider = None
    if not getattr(provider, "configured", False):
        raise AppError(
            "dev_observatory_ai_unavailable",
            "A IA não está configurada. Informe a chave no botão da IA no topo da tela.",
            status_code=409,
        )
    return provider


def _ai_status(request: Request) -> dict:
    _load_ai_override(request.app)
    provider = getattr(request.app.state, "devobs_ai_provider", None) or getattr(
        request.app.state, "ai_provider", None
    )
    try:
        _ai_provider(request)
        available = True
    except AppError:
        available = False
    profile_name = getattr(getattr(provider, "profile", None), "name", None)
    return {
        "available": available,
        "model": provider.model if available else None,
        "provider": profile_name if available else None,
        "configured_provider": profile_name,
        "key_set": bool(getattr(provider, "configured", False)),
        "from_screen": getattr(request.app.state, "devobs_ai_override", None) is not None,
        "suggestions": AI_MODEL_SUGGESTIONS,
    }


@router.put("/ai/config", dependencies=[Depends(_require_dev_observatory_csrf)])
def ai_config(
    payload: AIConfigRequest,
    request: Request,
    _user: SessionUser = Depends(require_dev_observatory_user),
):
    """Troca chave e modelo da IA do observatório (não a da gestão). A chave fica só em dev_reports/."""

    _recorder(request)
    state = request.app.state
    _load_ai_override(request.app)
    profile = PROFILES_BY_NAME[payload.provider]
    api_key = payload.api_key
    if not api_key:
        current = getattr(state, "devobs_ai_override", None)
        # Chave vazia só vale ao manter o mesmo provedor da chave já salva.
        if current and current["provider"] == profile.name:
            api_key = current["api_key"]
        elif getattr(state.ai_provider, "profile", None) is profile and state.settings.ai_configured:
            api_key = state.settings.ai_api_key
        else:
            raise AppError(
                "dev_observatory_ai_key_required",
                "Informe a chave deste provedor.",
                status_code=422,
            )
    provider = _build_ai_provider(
        state.settings, api_key=api_key, model=payload.model, base_url=profile.default_base_url
    )
    if not provider.configured:
        raise AppError("dev_observatory_ai_key_required", "Chave inválida.", status_code=422)
    path = _ai_override_path(state.settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"provider": profile.name, "model": payload.model, "api_key": api_key}),
        encoding="utf-8",
    )
    try:
        path.chmod(0o600)
    except OSError:
        pass
    state.devobs_ai_override = {"provider": profile.name, "model": payload.model, "api_key": api_key}
    state.devobs_ai_provider = provider
    return _ai_status(request)


@router.delete("/ai/config", dependencies=[Depends(_require_dev_observatory_csrf)])
def ai_config_reset(
    request: Request,
    _user: SessionUser = Depends(require_dev_observatory_user),
):
    """Descarta a chave da tela: o observatório volta a usar a IA do .env."""

    state = request.app.state
    _ai_override_path(state.settings).unlink(missing_ok=True)
    state.devobs_ai_override = None
    state.devobs_ai_provider = None
    return _ai_status(request)


def _terminate_allowed(settings) -> bool:
    # Lista permitida (SEC-03): só test/development; "prod", "real" ou
    # qualquer nome inesperado ficam bloqueados.
    return settings.development_tools_allowed


@router.post("/ai/diagnose", dependencies=[Depends(_require_dev_observatory_csrf)])
async def ai_diagnose(
    payload: DiagnoseRequest,
    request: Request,
    _user: SessionUser = Depends(require_dev_observatory_user),
):
    """Diagnóstico por IA de um evento (``sequence``) ou relatório (``report``).

    O cliente só aponta *qual* evidência; o texto enviado ao modelo sai do
    servidor, já sanitizado. Sem tools: a resposta é texto, nunca é executada.
    """

    if (payload.sequence is None) == (payload.report is None):
        raise AppError(
            "dev_observatory_diagnose_target",
            "Informe exatamente um entre 'sequence' e 'report'.",
            status_code=422,
        )
    recorder = _recorder(request)
    provider = _ai_provider(request)
    if payload.sequence is not None:
        event = next(
            (item for item in recorder.recent_events(limit=600) if item.get("sequence") == payload.sequence),
            None,
        )
        if event is None:
            raise AppError("event_not_found", "Evento fora da memória do observatório.", status_code=404)
        context = quick_fixes.event_context(event)
    else:
        text = _report_file(request, payload.report).read_text(encoding="utf-8")
        context = quick_fixes.report_context(text)
    async with _AI_LOCK:
        try:
            response = await provider.complete(
                quick_fixes.build_messages(context, payload.question),
                tools=[],
                request_id=f"devobs-{payload.sequence or payload.report}",
            )
        except AIProviderError as exc:
            raise AppError(
                "dev_observatory_ai_failed",
                exc.user_message,
                status_code=502,
            ) from exc
    return {
        "answer": (response.content or "").strip(),
        "model": provider.model,
        "usage": response.usage,
        "context_chars": len(context),
    }


@router.post("/ai/chat", dependencies=[Depends(_require_dev_observatory_csrf)])
async def ai_chat(
    payload: ChatRequest,
    request: Request,
    _user: SessionUser = Depends(require_dev_observatory_user),
):
    """Chat livre com a IA sobre erros. Mesmas garantias do diagnóstico:
    contexto montado e sanitizado no servidor, sem tools, uma chamada por vez."""

    if payload.messages[-1].role != "user":
        raise AppError("dev_observatory_chat_last_turn", "A última fala precisa ser do usuário.", status_code=422)
    recorder = _recorder(request)
    provider = _ai_provider(request)
    events = recorder.recent_events(limit=600)
    by_sequence = {item.get("sequence"): item for item in events}
    evidence = []
    for sequence in payload.sequences:
        event = by_sequence.get(sequence)
        if event is None:
            raise AppError("event_not_found", "Evento fora da memória do observatório.", status_code=404)
        evidence.append(quick_fixes.event_context(event))
    snapshot = (
        quick_fixes.snapshot_context(recorder.live_summary(), list(reversed(events)))
        if payload.include_snapshot
        else None
    )
    messages = quick_fixes.build_chat_messages([turn.model_dump() for turn in payload.messages], evidence, snapshot)
    async with _AI_LOCK:
        try:
            response = await provider.complete(messages, tools=[], request_id="devobs-chat")
        except AIProviderError as exc:
            raise AppError("dev_observatory_ai_failed", exc.user_message, status_code=502) from exc
    return {
        "answer": (response.content or "").strip(),
        "model": provider.model,
        "usage": response.usage,
        "context_chars": len(messages[0]["content"]),
    }


@router.post("/actions/terminate-backend", dependencies=[Depends(_require_dev_observatory_csrf)])
def terminate_backend(
    payload: TerminateBackendRequest,
    request: Request,
    _user: SessionUser = Depends(require_dev_observatory_user),
):
    """Encerra uma sessão travada do banco da API. Só no TESTE; nunca no REAL."""

    recorder = _recorder(request)
    if not _terminate_allowed(request.app.state.settings):
        raise AppError(
            "dev_observatory_action_forbidden",
            "Encerrar sessões do banco é permitido somente no ambiente de teste.",
            status_code=403,
        )
    result = quick_fixes.terminate_backend(_environment_database(request, TEST_ENVIRONMENT), payload.pid)
    if not result["found"]:
        raise AppError("backend_not_found", "Sessão não encontrada neste banco.", status_code=404)
    recorder.record_note(
        action="dev-observatory/terminate-backend",
        message=f"Sessão {payload.pid} encerrada pelo desenvolvedor" if result["terminated"]
        else f"Sessão {payload.pid} não pôde ser encerrada",
        details={"pid": payload.pid, "state": result["state"], "query": result["query"]},
    )
    return result


@router.post("/reports", dependencies=[Depends(_require_dev_observatory_csrf)])
def generate_report(
    payload: ReportRequest,
    request: Request,
    _user: SessionUser = Depends(require_dev_observatory_user),
):
    """Gera o relatório de uma janela. O ciclo automático usa o mesmo caminho."""

    recorder = _recorder(request)
    settings = request.app.state.settings
    clock = getattr(request.app.state, "clock", None)
    now = clock.now() if clock is not None else datetime.now()
    reference = payload.day or now.date()
    window = find_window(reference, payload.shift.strip())
    if window is None:
        raise AppError(
            "unknown_shift_window",
            "Janela de turno desconhecida. Use uma das chaves retornadas por /shifts.",
            status_code=404,
        )
    if report_exists(settings.dev_observatory_report_dir, window) and not payload.force:
        raise AppError(
            "report_already_generated",
            "Já existe relatório para esta janela. Use force=true para regravá-lo.",
            status_code=409,
        )
    written = write_shift_report(request.app, recorder, window, now)
    return {
        "ok": True,
        "window": window.as_dict(),
        "path": str(written),
        "name": window.directory_name,
    }


def write_shift_report(application, recorder, window, now: datetime) -> Path:
    """Escritor único do relatório de turno.

    O endpoint manual e o ciclo automático chamam exatamente esta função; não
    existe um segundo gerador que possa divergir do primeiro.
    """

    settings = application.state.settings
    try:
        environment = _api_environment(application)
    except Exception as exc:  # banco fora do ar não pode impedir o relatório
        environment = {"name": TEST_ENVIRONMENT, "database": None, "error": str(exc)}
    recorder.flush_metrics(force=True)
    payload = build_report(window, recorder, environment=environment, generated_at=now)
    written = write_report(settings.dev_observatory_report_dir, payload)
    recorder.record_note(
        action="dev_observatory.report",
        message=f"Relatório de turno gravado em {written.parent.name}.",
        details={
            "window": window.key,
            "defects": payload["summary"]["defects"],
            "expected_blocks": payload["summary"]["expected_blocks"],
        },
    )
    return written


# ---------------------------------------------------------------------------
# Página
# ---------------------------------------------------------------------------
_DENIED_PAGE = """<!doctype html>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Dev Observatory</title>
<style>
  body {{ font: 15px/1.6 system-ui, sans-serif; background:#0b0f14; color:#e6edf3;
         margin:0; padding:16px; box-sizing:border-box;
         display:grid; place-items:center; min-height:100vh; }}
  main {{ max-width: 520px; width: 100%; padding: 32px; border:1px solid #223; border-radius:12px;
          background:#111821; box-sizing: border-box; }}
</style>
<main>
  <h1>Dev Observatory</h1>
  <p>{message}</p>
</main>
"""

# Login próprio da ferramenta: não existe link para o /login do Gestor de
# Peças de propósito — as duas sessões são independentes (ver
# backend/api/dependencies/auth.py::require_dev_observatory_user).
_LOGIN_PAGE = """<!doctype html>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Dev Observatory</title>
<style>
  body { font: 15px/1.6 system-ui, sans-serif; background:#0b0f14; color:#e6edf3;
         margin:0; padding:16px; box-sizing:border-box;
         display:grid; place-items:center; min-height:100vh; }
  main { max-width: 360px; width: 100%; padding: 32px; border:1px solid #223; border-radius:12px;
          background:#111821; box-sizing: border-box; }
  h1 { margin: 0 0 4px; font-size: 20px; }
  p { margin: 0 0 20px; color: #9aa7b4; font-size: 13px; }
  label { display:block; margin-bottom: 12px; font-size: 13px; }
  input { display:block; width:100%; margin-top: 4px; padding: 8px 10px; border-radius: 6px;
           border: 1px solid #2a3a4d; background:#0b0f14; color:#e6edf3; box-sizing: border-box;
           font-size: 14px; }
  button { width:100%; padding: 9px; margin-top: 8px; border:0; border-radius:6px;
            background:#2563eb; color:#fff; font-weight:600; font-size: 14px; cursor:pointer; }
  button:disabled { opacity:.6; cursor:default; }
  input[aria-invalid=true] { border-color:#f87171; }
  #erro { color:#fca5a5; font-size:13px; min-height: 20px; margin-top: 8px; }
</style>
<main>
  <h1>Dev Observatory</h1>
  <p>Login próprio, independente do Gestor de Peças.</p>
  <form id="f" method="post" action="javascript:void(0)" novalidate>
    <label>Usuário<input name="username" autocomplete="username" required></label>
    <label>Senha<input name="password" type="password" autocomplete="current-password" required></label>
    <button type="submit">Entrar</button>
    <div id="erro" role="alert"></div>
  </form>
</main>
<script src="/dev-observatory/login.js"></script>
"""

# Script em arquivo próprio, não inline: o CSP das páginas fora de /api/ é
# `script-src 'self'` (sem `unsafe-inline`, de propósito) — um <script> inline
# aqui seria bloqueado pelo navegador, e o form cairia para o submit nativo
# (GET, credencial vazando na própria URL). Sem autenticação: é exatamente o
# script que faz o login acontecer.
_LOGIN_SCRIPT = """document.getElementById("f").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.target;
  const botao = form.querySelector("button");
  const erro = document.getElementById("erro");
  erro.textContent = "";
  // Validação própria em pt-BR (a nativa do navegador sai em inglês): foca o campo vazio.
  const vazio = ["username", "password"].map((nome) => form.elements[nome]).find((campo) => !campo.value.trim());
  for (const campo of form.querySelectorAll("input")) campo.removeAttribute("aria-invalid");
  if (vazio) {
    vazio.setAttribute("aria-invalid", "true");
    erro.textContent = `Preencha ${vazio.name === "username" ? "Usuário" : "Senha"}.`;
    vazio.focus();
    return;
  }
  botao.disabled = true;
  const dados = new FormData(form);
  try {
    const resposta = await fetch("/api/v1/dev-observatory/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username: dados.get("username"), password: dados.get("password") }),
    });
    if (resposta.ok) { window.location.reload(); return; }
    erro.textContent = resposta.status === 401 ? "Usuário ou senha inválidos." : "Não foi possível entrar agora.";
    if (resposta.status === 401) {
      form.elements.password.value = "";
      form.elements.password.focus();
    }
  } catch (falha) {
    erro.textContent = "Não foi possível falar com o servidor.";
  } finally {
    botao.disabled = false;
  }
});
"""


def _denied_page(message: str, status_code: int) -> HTMLResponse:
    """Página de recusa. A mensagem entra escapada, nunca como HTML.

    Hoje nenhuma mensagem que chega aqui carrega dado de quem chamou, mas o
    texto vem de uma exceção: escapar agora evita que uma mensagem futura
    (nome, código de OP, motivo vindo do banco) vire marcação na página.
    """

    return HTMLResponse(
        _DENIED_PAGE.format(message=html.escape(str(message))), status_code=status_code
    )


def _authorize_page(request: Request) -> SessionUser:
    return require_dev_observatory_user(request)


def _serve(filename: str, media_type: str) -> FileResponse:
    return FileResponse(
        PAGE_DIR / filename,
        media_type=media_type,
        headers={"Cache-Control": "no-store"},
    )


@page_router.get("")
def observatory_page(request: Request):
    try:
        _authorize_page(request)
    except AppError as exc:
        if exc.status_code == 401:
            return HTMLResponse(_LOGIN_PAGE, status_code=401)
        return _denied_page(exc.message, exc.status_code)
    except Exception:
        # Responde antes do login: o texto da exceção (host/usuário do banco)
        # fica só no log.
        LOGGER.exception("Falha ao autorizar a página do Dev Observatory")
        return _denied_page("Backend indisponível.", 503)
    return _serve("index.html", "text/html; charset=utf-8")


@page_router.get("/login.js")
def observatory_login_script():
    """Sem autenticação de propósito: é o script que faz o login acontecer."""

    return PlainTextResponse(
        _LOGIN_SCRIPT,
        media_type="text/javascript; charset=utf-8",
        headers={"Cache-Control": "no-store"},
    )


@page_router.get("/app.js")
def observatory_script(request: Request, _user: SessionUser = Depends(require_dev_observatory_user)):
    return _serve("app.js", "text/javascript; charset=utf-8")


@page_router.get("/app.css")
def observatory_style(request: Request, _user: SessionUser = Depends(require_dev_observatory_user)):
    return _serve("app.css", "text/css; charset=utf-8")
