from datetime import time
from typing import Any

from pydantic import BaseModel, Field


class ErrorResponse(BaseModel):
    code: str
    message: str
    request_id: str | None = None
    details: Any = None


class PageMeta(BaseModel):
    page: int
    page_size: int
    total: int
    pages: int



class AutomaticPauseRequest(BaseModel):
    """Pausa automática de um setor, mantida pela tela dos gestores."""

    id: int | None = None
    tipo_setor: str = Field(min_length=1, max_length=60)
    nome: str = Field(min_length=1, max_length=60)
    hora_inicio: time
    hora_fim: time
    ativo: bool = True
    ordem: int = Field(default=1, ge=1, le=99)


class OperatorBadgeRequest(BaseModel):
    """Crachá do chão de fábrica, mantido pela tela dos gestores (Wave 5).

    ``autorizador_retrabalho`` designa quem pode atender o chamado de
    retrabalho da primeira peça. É a mesma tabela de crachás que já existe:
    nenhum login novo e nenhuma autenticação paralela são criados.
    """

    cracha: str = Field(min_length=1, max_length=40)
    nome: str = Field(min_length=1, max_length=120)
    ativo: bool = True
    autorizador_retrabalho: bool = False
