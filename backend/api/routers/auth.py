import asyncio
from contextlib import asynccontextmanager
from functools import partial

import anyio
import anyio.to_thread
from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse

from app.core.areas import areas_for_user
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
from backend.api.security.login_throttle import login_throttle_key


router = APIRouter(prefix="/auth", tags=["Autenticação"])


# Atraso progressivo por IP+usuário — de propósito NÃO é um bloqueio total
# como o do Dev Observatory: este é o login do chão de fábrica, e um operador
# que erra a senha num terminal compartilhado não pode ficar impedido de
# apontar produção. O atraso torna adivinhação automatizada impraticável sem
# nunca recusar uma tentativa legítima (achado A2 da auditoria de segurança
# de 2026-09-14).
#
# O atraso sozinho não freia uma RAJADA paralela: N requisições simultâneas
# dormiriam cada uma no máximo o teto e testariam a senha juntas. Por isso as
# tentativas da MESMA chave IP+usuário passam uma de cada vez (lock por chave
# abaixo): a taxa por chave fica em no máximo 1 tentativa por atraso, sem
# nunca recusar. Chaves diferentes (outro operador, outro terminal) não se
# esperam entre si.
LOGIN_DELAY_BASE_SECONDS = 0.5
LOGIN_DELAY_MAX_SECONDS = 8.0
LOGIN_DELAY_WINDOW_SECONDS = 300

# ponytail: o lock é por processo (API roda com 1 worker uvicorn). Se virar
# multi-worker, cada worker serializa só a própria fila; o upgrade é um
# advisory lock no PostgreSQL pela chave (pg_advisory_xact_lock(hashtext(...))).
_login_locks: dict[str, asyncio.Lock] = {}
_login_waiters: dict[str, int] = {}


@asynccontextmanager
async def _serialized_login(key: str):
    """Uma tentativa por vez por chave; a entrada some quando ninguém espera."""

    # Sem ``await`` entre ler e gravar o dict: no event loop isto é atômico.
    lock = _login_locks.setdefault(key, asyncio.Lock())
    _login_waiters[key] = _login_waiters.get(key, 0) + 1
    try:
        async with lock:
            yield
    finally:
        _login_waiters[key] -= 1
        if not _login_waiters[key]:
            del _login_waiters[key]
            _login_locks.pop(key, None)


def _login_delay_for_failures(failures: int) -> float:
    failures = int(failures or 0)
    if failures <= 0:
        return 0.0
    return min(LOGIN_DELAY_MAX_SECONDS, LOGIN_DELAY_BASE_SECONDS * (2 ** (failures - 1)))


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
    throttle_key = login_throttle_key(request, payload.username)
    # O contador vive no PostgreSQL (`login_throttle`): compartilhado entre
    # workers e reinícios, sem um segundo caminho em memória (BK-22).
    #
    # A reserva (increment atômico) acontece ANTES da tentativa de senha, não
    # depois de uma falha: se fosse ler o contador antes e só incrementar
    # depois de autenticar (como era), N requisições concorrentes com a mesma
    # chave leriam o mesmo contador desatualizado, aplicariam o mesmo atraso
    # (ou nenhum) e tentariam a senha ao mesmo tempo — o throttle nunca
    # freava uma rajada, só tentativas em sequência. `registrar_falha_login`
    # já é atômico (INSERT ... ON CONFLICT ... RETURNING no Postgres), então
    # reservar aqui serializa a rajada em contadores crescentes de verdade
    # (achado M1 da auditoria). Sucesso limpa o contador logo abaixo.
    #
    # Reserva → atraso → verificação rodam sob o lock da chave: a rajada da
    # mesma chave vira fila, e cada uma paga o atraso da falha anterior.
    async with _serialized_login(throttle_key):
        failures = await anyio.to_thread.run_sync(
            partial(
                database.registrar_falha_login,
                throttle_key,
                janela_segundos=LOGIN_DELAY_WINDOW_SECONDS,
            ),
            limiter=request.app.state.auth_thread_limiter,
        )
        # O contador já inclui a tentativa atual (reserva acima): o atraso é
        # pelas falhas ANTERIORES, para que o primeiro login do turno não
        # espere nada.
        delay = _login_delay_for_failures(failures - 1)
        if delay:
            await anyio.sleep(delay)
        # O hash da senha (PBKDF2, 600 mil iterações) é caro de propósito — é
        # o piso de segurança recomendado. Ele roda numa capacity limiter
        # PRÓPRIA (``auth_thread_limiter``), separada da threadpool geral das
        # rotas leves do posto: assim um pico de logins simultâneos no início
        # do turno não enfileira quem já está com a tela aberta atrás da
        # verificação de senha de quem está entrando (medido no teste de carga
        # de conexão).
        user = await anyio.to_thread.run_sync(
            partial(database.autenticar_usuario, payload.username, payload.password),
            limiter=request.app.state.auth_thread_limiter,
        )
        if not user:
            # A falha já foi reservada/contada ANTES da tentativa (acima); não
            # incrementa de novo aqui.
            raise AppError(
                "invalid_credentials",
                "Usuário ou senha inválidos.",
                status_code=401,
            )
        await anyio.to_thread.run_sync(
            partial(database.limpar_falhas_login, throttle_key),
            limiter=request.app.state.auth_thread_limiter,
        )
    role = normalize_user_level(user.get("nivel"))
    if role is None:
        raise AppError(
            "user_role_invalid",
            "A conta não possui um perfil de acesso válido.",
            status_code=403,
        )
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
        areas=areas_for_user(user.get("nivel_atribuido"), role),
    )
    token, claims = request.app.state.session_signer.issue(
        user_id=session_user.id,
        username=session_user.name,
        role=session_user.role,
        session_version=int(user.get("session_version") or 0),
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
def logout(
    request: Request,
    user: SessionUser = Depends(get_current_user),
    database=Depends(get_database),
):
    # Revoga o token no servidor (bump de session_version) além de apagar o
    # cookie: sem isso, um cookie roubado/copiado continuava válido até
    # expirar sozinho mesmo depois do usuário clicar em Sair (achado B1 da
    # auditoria de segurança). Mesmo mecanismo já usado em troca de senha,
    # de nível e desativação de usuário — aqui derruba também outros
    # terminais logados na mesma conta, comportamento já aceito nesses
    # outros pontos.
    database.revogar_sessoes_usuario(user.id)
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
