"""Regras de senha por tipo de conta (auditoria 14/10/2026, SEC-05 e A6).

Os terminais do chão de fábrica (operadores, Andon, almoxarifado) seguem com a
senha padrão e o mínimo de 6 caracteres: trocar isso pararia o apontamento.
As contas de gestão enxergam a fábrica inteira e o cadastro, então pedem uma
senha própria, mais longa, e não podem continuar na senha padrão.
"""

import hmac

from app.core.permissions import can_access_management_web

DEFAULT_PASSWORD = "123456"
MIN_PASSWORD_LENGTH = 6
MIN_MANAGEMENT_PASSWORD_LENGTH = 8


def is_management_level(level) -> bool:
    return can_access_management_web(level)


def password_change_required(level, password: str) -> bool:
    """Conta de gestão que entrou com a senha padrão precisa definir outra."""

    return is_management_level(level) and hmac.compare_digest(
        str(password).encode("utf-8"), DEFAULT_PASSWORD.encode("utf-8")
    )


def password_policy_error(level, password: str) -> str | None:
    """Mensagem para a tela quando a senha não serve para este nível; ``None`` se serve."""

    if not is_management_level(level):
        if len(password) < MIN_PASSWORD_LENGTH:
            return f"A senha precisa ter pelo menos {MIN_PASSWORD_LENGTH} caracteres."
        return None
    if password == DEFAULT_PASSWORD:
        return "Escolha uma senha diferente da senha padrão."
    if len(password) < MIN_MANAGEMENT_PASSWORD_LENGTH:
        return (
            f"Contas de gestão precisam de senha com pelo menos "
            f"{MIN_MANAGEMENT_PASSWORD_LENGTH} caracteres."
        )
    return None
