"""Autenticação e autorização baseadas no usuário PostgreSQL atual."""

from __future__ import annotations

import hmac

from fastapi import Depends, Request

from app.core.permissions import (
    can_access_andon_web,
    can_access_management_web,
    is_sector_operator,
    normalize_user_level,
    operator_sector_for_user_level,
)
from backend.api.database import get_database
from backend.api.errors import AppError
from backend.api.schemas.auth import SessionUser


def get_current_user(request: Request, database=Depends(get_database)) -> SessionUser:
    settings = request.app.state.settings
    token = request.cookies.get(settings.session_cookie_name)
    if not token:
        raise AppError("authentication_required", "Entre para continuar.", status_code=401)
    claims = request.app.state.session_signer.decode(token)
    loader = getattr(database, "obter_usuario_por_id", None)
    row = loader(claims.user_id) if callable(loader) else None
    if not row or not bool(row.get("ativo")):
        raise AppError(
            "session_user_unavailable",
            "O usuário da sessão não está ativo.",
            status_code=401,
        )
    if int(claims.session_version) != int(row.get("session_version") or 0):
        raise AppError(
            "session_revoked",
            "A sessão foi invalidada. Entre novamente.",
            status_code=401,
        )
    role = normalize_user_level(row.get("nivel"))
    if role is None:
        raise AppError(
            "session_user_role_invalid",
            "A conta não possui um perfil de acesso válido.",
            status_code=403,
        )
    operator_sector = operator_sector_for_user_level(role)
    request.state.session_claims = claims
    return SessionUser(
        id=int(row["id"]),
        name=str(row.get("nome") or claims.username),
        role=role,
        management_access=can_access_management_web(role),
        andon_access=can_access_andon_web(role),
        operator_access=is_sector_operator(role),
        operator_sector=operator_sector.name if operator_sector else None,
        operator_resources=operator_sector.resources if operator_sector else (),
        operator_automatic_queue=operator_sector.automatic_queue if operator_sector else False,
    )


def require_management_user(user: SessionUser = Depends(get_current_user)) -> SessionUser:
    if not user.management_access:
        raise AppError(
            "management_access_denied",
            "Seu perfil não possui acesso à área gerencial.",
            status_code=403,
        )
    return user


def require_admin_user(user: SessionUser = Depends(get_current_user)) -> SessionUser:
    """Nível acima da gestão comum — só quem tem ``nivel = 'admin'``.

    Usado para o que a gestão não deve poder fazer sozinha: cadastro de
    usuários e a lista de contatos de chamada (decisão do usuário, 14/09/2026).
    """

    if user.role != "admin":
        raise AppError(
            "admin_access_denied",
            "Só a conta administradora tem acesso a esta área.",
            status_code=403,
        )
    return user


def require_dev_observatory_user(request: Request) -> SessionUser:
    """Porta do Dev Observatory — login próprio, isolado do login principal.

    Não usa ``get_current_user`` nem a tabela ``usuarios``: credencial e cookie
    de sessão vivem só neste caminho (ver ``backend/api/routers/dev_observatory.py``
    e ``backend/api/config.py``). A ferramenta expõe stack trace, catálogo do
    PostgreSQL e leitura do ambiente REAL — de propósito ela não compartilha
    nada com o login operacional, para que um problema num nunca afete o outro.
    """

    settings = request.app.state.settings
    token = request.cookies.get(settings.dev_observatory_cookie_name)
    if not token:
        raise AppError(
            "dev_observatory_authentication_required",
            "Entre no Dev Observatory para continuar.",
            status_code=401,
        )
    claims = request.app.state.dev_observatory_session_signer.decode(token)
    return SessionUser(
        id=0,
        name=claims.username,
        role="dev_observatory",
        management_access=False,
        andon_access=False,
        operator_access=False,
    )


def require_andon_user(user: SessionUser = Depends(get_current_user)) -> SessionUser:
    if not user.andon_access:
        raise AppError(
            "andon_access_denied",
            "Seu perfil não possui acesso ao Andon Geral.",
            status_code=403,
        )
    return user


def require_operator_user(user: SessionUser = Depends(get_current_user)) -> SessionUser:
    if not user.operator_access:
        raise AppError(
            "operator_access_denied",
            "Seu perfil não possui acesso à área do operador.",
            status_code=403,
        )
    return user


def require_csrf(request: Request, _user: SessionUser = Depends(get_current_user)) -> None:
    settings = request.app.state.settings
    claims = getattr(request.state, "session_claims", None)
    header_value = request.headers.get("X-CSRF-Token", "")
    cookie_value = request.cookies.get(settings.csrf_cookie_name, "")
    expected = claims.csrf if claims is not None else ""
    if not expected or not hmac.compare_digest(header_value, expected) or not hmac.compare_digest(
        cookie_value, expected
    ):
        raise AppError(
            "csrf_validation_failed",
            "A validação de segurança da sessão falhou.",
            status_code=403,
        )
