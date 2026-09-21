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
Nenhum endpoint deste módulo escreve em banco — nem no TESTE — e nada aqui fala
com TOTVS ou SigmaNEST.
"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
import html
import secrets
import threading
import time

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, Response
from pydantic import BaseModel, ConfigDict, Field

from backend.api.dependencies.auth import require_dev_observatory_user
from backend.api.dependencies.filters import analytics_filter
from backend.api.errors import AppError
from backend.api.schemas.auth import SessionUser
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
from mes.contracts import AnalyticsFilter
from mes.services.frontend_facade import FrontendBackendFacade


router = APIRouter(prefix="/dev-observatory", tags=["Dev Observatory"])
page_router = APIRouter(prefix="/dev-observatory", include_in_schema=False)

PAGE_DIR = Path(__file__).resolve().parents[2] / "observability" / "page"

TEST_ENVIRONMENT = "test"
REAL_ENVIRONMENT = "real"


class ReportRequest(BaseModel):
    """Geração manual de um relatório de turno já encerrado (ou em curso)."""

    model_config = ConfigDict(extra="forbid")

    day: date | None = None
    shift: str = Field(default="turno", max_length=32)
    force: bool = False


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


# Freio de adivinhação de senha. Atrás desta única credencial estão stack
# trace, catálogo do PostgreSQL e leitura do ambiente REAL — e o Gestor é
# publicado por hostname externo (``GESTOR_WEB_PUBLIC_HOST``). Sem freio, a
# senha fica exposta a tentativa ilimitada por quem alcançar a URL.
LOGIN_MAX_FAILURES = 5
LOGIN_LOCKOUT_SECONDS = 300
_login_failures: dict[str, tuple[int, float]] = {}
_login_failures_lock = threading.Lock()


def _login_client_key(request: Request) -> str:
    client = request.client
    return str(getattr(client, "host", "") or "desconhecido")


def _login_lockout_remaining(key: str, *, now: float) -> int:
    """Segundos restantes de bloqueio, ou 0 quando a tentativa é permitida."""

    with _login_failures_lock:
        failures, until = _login_failures.get(key, (0, 0.0))
        if failures < LOGIN_MAX_FAILURES:
            return 0
        if now >= until:
            # Janela vencida: o contador recomeça do zero.
            _login_failures.pop(key, None)
            return 0
        return max(1, int(until - now))


def _register_login_failure(key: str, *, now: float) -> None:
    with _login_failures_lock:
        # Descarta as janelas já vencidas antes de contar: sem isto a tabela
        # cresceria sem limite e falhas separadas por horas somariam como se
        # fossem seguidas.
        for vencida in [k for k, (_f, until) in _login_failures.items() if now >= until]:
            _login_failures.pop(vencida, None)
        failures, _until = _login_failures.get(key, (0, 0.0))
        _login_failures[key] = (failures + 1, now + LOGIN_LOCKOUT_SECONDS)


def _clear_login_failures(key: str) -> None:
    with _login_failures_lock:
        _login_failures.pop(key, None)


def _credential_matches(sent: str, configured: str) -> bool:
    """Comparação em tempo constante que aceita qualquer caractere.

    ``secrets.compare_digest`` levanta ``TypeError`` quando recebe ``str`` com
    caractere fora do ASCII — uma senha acentuada derrubava o endpoint com 500
    em vez de recusar com 401. Em bytes UTF-8 a comparação vale para qualquer
    senha e continua sem vazar tempo.
    """

    return secrets.compare_digest(sent.encode("utf-8"), configured.encode("utf-8"))


@router.post("/login")
def dev_observatory_login(payload: DevObservatoryLoginRequest, request: Request):
    settings = request.app.state.settings
    now = time.monotonic()
    client_key = _login_client_key(request)
    remaining = _login_lockout_remaining(client_key, now=now)
    if remaining:
        raise AppError(
            "dev_observatory_login_blocked",
            f"Muitas tentativas seguidas. Aguarde {remaining}s para tentar de novo.",
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
        _register_login_failure(client_key, now=now)
        raise AppError(
            "dev_observatory_invalid_credentials",
            "Usuário ou senha inválidos.",
            status_code=401,
        )
    _clear_login_failures(client_key)
    token, _claims = request.app.state.dev_observatory_session_signer.issue(
        user_id=0, username=payload.username, role="dev_observatory",
    )
    response = JSONResponse(content={"username": payload.username})
    response.set_cookie(
        settings.dev_observatory_cookie_name,
        token,
        httponly=True,
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
        "report_dir": str(settings.dev_observatory_report_dir),
        "write_policy": {
            "database_writes": "nenhuma — o observatório persiste apenas em disco",
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
    filters: AnalyticsFilter = Depends(analytics_filter),
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
        "directory": str(settings.dev_observatory_report_dir),
    }


@router.get("/reports/{name}", response_class=PlainTextResponse)
def report_content(
    name: str,
    request: Request,
    _user: SessionUser = Depends(require_dev_observatory_user),
):
    settings = request.app.state.settings
    base = Path(settings.dev_observatory_report_dir).resolve()
    target = (base / name / "report.md").resolve()
    # Travessia de diretório é recusada explicitamente: o nome vem da URL.
    if base not in target.parents or not target.is_file():
        raise AppError("report_not_found", "Relatório não encontrado.", status_code=404)
    return PlainTextResponse(
        target.read_text(encoding="utf-8"),
        media_type="text/markdown; charset=utf-8",
    )


# Sem `require_csrf`: esse guard lê o CSRF da sessão PRINCIPAL, que este
# router não usa mais. SameSite=Strict no cookie de sessão do observatório já
# barra o POST vindo de outra origem, proporcional ao risco de uma ferramenta
# interna de um único operador.
@router.post("/reports")
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
  #erro { color:#f87171; font-size:12px; min-height: 16px; margin-top: 8px; }
</style>
<main>
  <h1>Dev Observatory</h1>
  <p>Login próprio, independente do Gestor de Peças.</p>
  <form id="f" method="post" action="javascript:void(0)">
    <label>Usuário<input name="username" autocomplete="username" required></label>
    <label>Senha<input name="password" type="password" autocomplete="current-password" required></label>
    <button type="submit">Entrar</button>
    <div id="erro"></div>
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
    except Exception as exc:
        return _denied_page(f"Backend indisponível: {exc}", 503)
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
