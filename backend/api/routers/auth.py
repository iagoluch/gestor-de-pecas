from functools import partial
import threading
import time

import anyio
import anyio.to_thread
from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse

from app.core.permissions import (
    can_access_andon_web,
    can_access_management_web,
    is_sector_operator,
    normalize_user_level,
    operator_sector_for_user_level,
)
from backend.api.database import get_database
from backend.api.dependencies.auth import get_current_user, require_csrf
from backend.api.errors import AppError
from backend.api.schemas.auth import LoginRequest, SessionUser


router = APIRouter(prefix="/auth", tags=["Autenticação"])


# Atraso progressivo por IP+usuário — de propósito NÃO é um bloqueio total
# como o do Dev Observatory: este é o login do chão de fábrica, e um operador
# que erra a senha num terminal compartilhado não pode ficar impedido de
# apontar produção. O atraso torna adivinhação automatizada impraticável sem
# nunca recusar uma tentativa legítima (achado A2 da auditoria de segurança
# de 2026-09-14).
LOGIN_DELAY_BASE_SECONDS = 0.5
LOGIN_DELAY_MAX_SECONDS = 8.0
LOGIN_DELAY_WINDOW_SECONDS = 300
_login_failures: dict[str, tuple[int, float]] = {}
_login_failures_lock = threading.Lock()


def _login_throttle_key(request: Request, username: str) -> str:
    client = request.client
    ip = str(getattr(client, "host", "") or "desconhecido")
    return f"{ip}:{username.strip().casefold()}"


def _login_delay_seconds(key: str, *, now: float) -> float:
    with _login_failures_lock:
        failures, last_seen = _login_failures.get(key, (0, 0.0))
        if failures == 0 or now - last_seen > LOGIN_DELAY_WINDOW_SECONDS:
            return 0.0
        return min(LOGIN_DELAY_MAX_SECONDS, LOGIN_DELAY_BASE_SECONDS * (2 ** (failures - 1)))


def _register_login_failure(key: str, *, now: float) -> None:
    with _login_failures_lock:
        for vencida in [
            k for k, (_f, seen) in _login_failures.items() if now - seen > LOGIN_DELAY_WINDOW_SECONDS
        ]:
            _login_failures.pop(vencida, None)
        failures, _seen = _login_failures.get(key, (0, 0.0))
        _login_failures[key] = (failures + 1, now)


def _clear_login_failures(key: str) -> None:
    with _login_failures_lock:
        _login_failures.pop(key, None)


def _cookie_options(request: Request):
    settings = request.app.state.settings
    return {
        "secure": settings.cookie_secure,
        "samesite": "strict",
        "path": "/",
        "max_age": settings.session_ttl_seconds,
    }


@router.post("/login", response_model=SessionUser)
async def login(payload: LoginRequest, request: Request, database=Depends(get_database)):
    now = time.monotonic()
    throttle_key = _login_throttle_key(request, payload.username)
    delay = _login_delay_seconds(throttle_key, now=now)
    if delay:
        await anyio.sleep(delay)
    # O hash da senha (PBKDF2, 600 mil iterações) é caro de propósito — é o
    # piso de segurança recomendado. Ele roda numa capacity limiter PRÓPRIA
    # (``auth_thread_limiter``), separada da threadpool geral das rotas
    # leves do posto: assim um pico de logins simultâneos no início do turno
    # não enfileira quem já está com a tela aberta atrás da verificação de
    # senha de quem está entrando (medido no teste de carga de conexão).
    user = await anyio.to_thread.run_sync(
        partial(database.autenticar_usuario, payload.username, payload.password),
        limiter=request.app.state.auth_thread_limiter,
    )
    if not user:
        _register_login_failure(throttle_key, now=time.monotonic())
        raise AppError(
            "invalid_credentials",
            "Usuário ou senha inválidos.",
            status_code=401,
        )
    _clear_login_failures(throttle_key)
    role = normalize_user_level(user.get("nivel"))
    operator_sector = operator_sector_for_user_level(role)
    session_user = SessionUser(
        id=int(user["id"]),
        name=str(user.get("nome") or payload.username),
        role=role,
        management_access=can_access_management_web(role),
        andon_access=can_access_andon_web(role),
        operator_access=is_sector_operator(role),
        operator_sector=operator_sector.name if operator_sector else None,
        operator_resources=operator_sector.resources if operator_sector else (),
        operator_automatic_queue=operator_sector.automatic_queue if operator_sector else False,
    )
    token, claims = request.app.state.session_signer.issue(
        user_id=session_user.id,
        username=session_user.name,
        role=session_user.role,
    )
    options = _cookie_options(request)
    response = JSONResponse(content=session_user.model_dump())
    response.set_cookie(
        request.app.state.settings.session_cookie_name,
        token,
        httponly=True,
        **options,
    )
    response.set_cookie(
        request.app.state.settings.csrf_cookie_name,
        claims.csrf,
        httponly=False,
        **options,
    )
    response.headers["Cache-Control"] = "no-store"
    return response


@router.get("/session", response_model=SessionUser)
def session(user: SessionUser = Depends(get_current_user)):
    return user


@router.post("/logout", status_code=204, dependencies=[Depends(require_csrf)])
def logout(request: Request):
    response = Response(status_code=204)
    settings = request.app.state.settings
    response.delete_cookie(
        settings.session_cookie_name,
        path="/",
        secure=settings.cookie_secure,
        samesite="strict",
    )
    response.delete_cookie(
        settings.csrf_cookie_name,
        path="/",
        secure=settings.cookie_secure,
        samesite="strict",
    )
    response.headers["Cache-Control"] = "no-store"
    return response
