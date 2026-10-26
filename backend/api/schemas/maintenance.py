"""Contrato das sugestões de manutenção (migration 68)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class MaintenanceDecisionRequest(BaseModel):
    """Corpo opcional de aceitar/descartar. ``nota`` vazia vira ausência."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    nota: str | None = Field(default=None, max_length=500)
