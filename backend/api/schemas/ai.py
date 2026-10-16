from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from mes.contracts import MAX_AI_CONVERSATION_TITLE_CHARS, MAX_AI_MESSAGE_CHARS


class AIConversationCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    title: str | None = Field(default=None, max_length=MAX_AI_CONVERSATION_TITLE_CHARS)

    @field_validator("title")
    @classmethod
    def non_empty_title(cls, value):
        if value is not None and not value.strip():
            raise ValueError("O título não pode ficar vazio.")
        return value


class ExplanationFilters(BaseModel):
    """Mesmos filtros de ``GET /management/explicacao`` (nomes e limites iguais)."""

    model_config = ConfigDict(extra="forbid")

    inicio: datetime | None = None
    fim: datetime | None = None
    setor: str | None = Field(default=None, max_length=120)
    recurso: str | None = Field(default=None, max_length=120)
    turno: str | None = Field(default=None, max_length=80)
    op: str | None = Field(default=None, max_length=120)
    operacao: str | None = Field(default=None, max_length=120)
    produto: str | None = Field(default=None, max_length=160)
    operador: str | None = Field(default=None, max_length=160)


class ExplanationRef(BaseModel):
    """Referência à explicação aberta no painel: só métrica + filtros.

    A árvore nunca vem do cliente; o servidor a recalcula a cada mensagem.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    metric: str = Field(min_length=1, max_length=64)
    filters: ExplanationFilters = Field(default_factory=ExplanationFilters)


class AIMessageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    content: str = Field(min_length=1, max_length=MAX_AI_MESSAGE_CHARS)
    retry: bool = False
    explanation: ExplanationRef | None = None
