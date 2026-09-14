"""Contratos neutros da IA Industrial, sem dependência de FastAPI ou Groq."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterable
from dataclasses import dataclass, field
from typing import Any, Protocol


MAX_AI_MESSAGE_CHARS = 4_000
MAX_AI_CONVERSATION_TITLE_CHARS = 160


class AIServiceError(RuntimeError):
    def __init__(
        self,
        code: str,
        user_message: str,
        *,
        retryable: bool = False,
        technical_details: dict[str, Any] | None = None,
    ):
        super().__init__(user_message)
        self.code = code
        self.user_message = user_message
        self.retryable = retryable
        self.technical_details = dict(technical_details or {})


class AIUnavailableError(AIServiceError):
    pass


class AIConversationNotFoundError(AIServiceError):
    pass


class AIToolError(AIServiceError):
    pass


class AIProviderError(AIServiceError):
    pass


@dataclass(frozen=True)
class AIServiceConfig:
    enabled: bool
    configured: bool
    model: str
    max_tool_rounds: int = 6
    max_history_messages: int = 20
    request_token_budget: int = 6_000
    max_completion_tokens: int = 640


@dataclass(frozen=True)
class AIRequestContext:
    user_id: int
    management_access: bool
    request_id: str | None = None


@dataclass(frozen=True)
class AIToolCall:
    id: str
    name: str
    arguments: str


@dataclass(frozen=True)
class AIProviderResponse:
    content: str | None
    tool_calls: tuple[AIToolCall, ...] = ()
    assistant_message: dict[str, Any] = field(default_factory=dict)
    usage: dict[str, Any] = field(default_factory=dict)
    finish_reason: str | None = None


@dataclass(frozen=True)
class AIStreamEvent:
    event: str
    data: dict[str, Any]


class AIProvider(Protocol):
    async def complete(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]],
        tool_choice: str = "auto",
        request_id: str | None = None,
    ) -> AIProviderResponse: ...

    def stream(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str = "none",
        request_id: str | None = None,
    ) -> AsyncIterator[str]: ...


class AIConversationRepository(Protocol):
    def criar_conversa_ia(self, user_id: int, title: str) -> dict[str, Any]: ...

    def listar_conversas_ia(self, user_id: int, *, limit: int = 100) -> list[dict[str, Any]]: ...

    def obter_conversa_ia(
        self,
        conversation_id: int,
        user_id: int,
        *,
        message_limit: int | None = None,
    ) -> dict[str, Any] | None: ...

    def atualizar_titulo_conversa_ia(
        self,
        conversation_id: int,
        user_id: int,
        title: str,
    ) -> dict[str, Any] | None: ...

    def excluir_conversa_ia(self, conversation_id: int, user_id: int) -> bool: ...

    def adicionar_mensagem_ia(
        self,
        conversation_id: int,
        user_id: int,
        role: str,
        content: str,
        *,
        model: str | None = None,
        metadata: dict | None = None,
    ) -> dict[str, Any] | None: ...

    def listar_conhecimento_ia_validado(self, *, limit: int = 100) -> Iterable[dict[str, Any]]: ...
