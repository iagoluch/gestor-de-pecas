"""Contrato HTTP do log "quem mudou o quê" (migration 66)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel


class AuditEntry(BaseModel):
    id: int
    quando: datetime
    usuario_id: int | None = None
    usuario_nome: str | None = None
    entidade: str
    chave: str
    acao: Literal["criar", "alterar", "excluir"]
    antes: dict[str, Any] | None = None
    depois: dict[str, Any] | None = None


class AuditResponse(BaseModel):
    items: list[AuditEntry]
    count: int
