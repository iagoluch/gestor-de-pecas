"""Dependências da API operacional, sempre derivadas do perfil autenticado."""

from app.core.permissions import operator_sector_for_user_level
from backend.api.errors import AppError
from backend.api.schemas.auth import SessionUser


def sector_for_user(user: SessionUser):
    sector = operator_sector_for_user_level(user.role)
    if sector is None:
        raise AppError(
            "operator_sector_unavailable",
            "O perfil não possui um setor operacional configurado.",
            status_code=403,
        )
    return sector


def validate_resource(user: SessionUser, resource: str):
    sector = sector_for_user(user)
    value = str(resource or "").strip()
    if value not in sector.resources:
        raise AppError(
            "operator_resource_denied",
            "O recurso informado não pertence ao setor do operador.",
            status_code=403,
        )
    return sector, value
