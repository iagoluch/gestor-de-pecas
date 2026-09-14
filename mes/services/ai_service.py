"""Orquestra memória, tool calling e resposta da IA sem depender de HTTP."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

from mes.ai.context_budget import build_budgeted_context, fit_messages_to_budget
from mes.ai.prompts import FINAL_RESPONSE_INSTRUCTION
from mes.contracts.ai import (
    AIConversationNotFoundError,
    AIRequestContext,
    AIServiceConfig,
    AIServiceError,
    AIStreamEvent,
    AIToolError,
    AIUnavailableError,
    MAX_AI_CONVERSATION_TITLE_CHARS,
    MAX_AI_MESSAGE_CHARS,
)


class AIService:
    def __init__(self, repository, provider, tools, config: AIServiceConfig):
        self.repository = repository
        self.provider = provider
        self.tools = tools
        self.config = config

    def status(self) -> dict[str, Any]:
        return {
            "enabled": bool(self.config.enabled),
            "configured": bool(self.config.configured),
            "model": self.config.model,
            "available": bool(self.config.enabled and self.config.configured),
        }

    def _ensure_available(self, context: AIRequestContext | None = None):
        if context is not None and not context.management_access:
            raise AIUnavailableError(
                "management_access_denied",
                "Seu perfil não possui acesso à IA gerencial.",
            )
        if not self.config.enabled:
            raise AIUnavailableError(
                "ai_disabled",
                "A IA Industrial está desabilitada no servidor.",
            )
        if not self.config.configured:
            raise AIUnavailableError(
                "ai_not_configured",
                "IA não configurada. Defina a chave da Groq no servidor.",
            )

    @staticmethod
    def _title_from_question(question: str) -> str:
        title = " ".join(str(question).split())
        if len(title) > MAX_AI_CONVERSATION_TITLE_CHARS:
            title = title[: MAX_AI_CONVERSATION_TITLE_CHARS - 1].rstrip() + "…"
        return title or "Nova conversa"

    def create_conversation(self, user_id: int, title: str | None = None):
        clean_title = self._title_from_question(title) if title else "Nova conversa"
        return self.repository.criar_conversa_ia(user_id, clean_title)

    def list_conversations(self, user_id: int):
        items = self.repository.listar_conversas_ia(user_id, limit=100)
        return {"items": items, "count": len(items)}

    def get_conversation(self, conversation_id: int, user_id: int):
        conversation = self.repository.obter_conversa_ia(conversation_id, user_id)
        if conversation is None:
            raise AIConversationNotFoundError(
                "ai_conversation_not_found",
                "Conversa não encontrada.",
            )
        return conversation

    def delete_conversation(self, conversation_id: int, user_id: int) -> None:
        if not self.repository.excluir_conversa_ia(conversation_id, user_id):
            raise AIConversationNotFoundError(
                "ai_conversation_not_found",
                "Conversa não encontrada.",
            )

    @staticmethod
    def _merge_usage(target: dict[str, int], usage: dict[str, Any]):
        for key, value in usage.items():
            if isinstance(value, int):
                target[key] = target.get(key, 0) + value

    async def stream_message(
        self,
        conversation_id: int,
        content: str,
        context: AIRequestContext,
        *,
        retry: bool = False,
    ):
        started = time.monotonic()
        tools_called: list[str] = []
        artifacts: list[dict[str, Any]] = []
        usage: dict[str, int] = {}
        success = False
        self._ensure_available(context)
        question = str(content or "").strip()
        if not question:
            raise AIServiceError("ai_message_empty", "Digite uma pergunta para continuar.")
        if len(question) > MAX_AI_MESSAGE_CHARS:
            raise AIServiceError(
                "ai_message_too_large",
                f"A pergunta deve ter no máximo {MAX_AI_MESSAGE_CHARS} caracteres.",
            )

        conversation = self.repository.obter_conversa_ia(
            conversation_id,
            context.user_id,
            message_limit=1,
        )
        if conversation is None:
            raise AIConversationNotFoundError(
                "ai_conversation_not_found",
                "Conversa não encontrada.",
            )
        existing_messages = list(conversation.get("messages") or [])
        if retry:
            last = existing_messages[-1] if existing_messages else None
            if not last or last.get("role") != "user" or str(last.get("content") or "") != question:
                raise AIServiceError(
                    "ai_retry_unavailable",
                    "Não há uma pergunta pendente compatível para tentar novamente.",
                )
            user_message = last
        else:
            user_message = self.repository.adicionar_mensagem_ia(
                conversation_id,
                context.user_id,
                "user",
                question,
            )
            if user_message is None:
                raise AIConversationNotFoundError(
                    "ai_conversation_not_found",
                    "Conversa não encontrada.",
                )
            if not existing_messages and str(conversation.get("title")) == "Nova conversa":
                self.repository.atualizar_titulo_conversa_ia(
                    conversation_id,
                    context.user_id,
                    self._title_from_question(question),
                )

        yield AIStreamEvent(
            "status",
            {"message": "Preparando a consulta…", "user_message_id": user_message.get("id")},
        )

        history = self.repository.obter_conversa_ia(
            conversation_id,
            context.user_id,
            message_limit=self.config.max_history_messages,
        )
        knowledge = self.repository.listar_conhecimento_ia_validado(limit=20)
        rounds = 0
        limit_reached = False
        selected_tools = self.tools.select_schemas(question)
        messages, context_metrics = build_budgeted_context(
            history=history.get("messages") or [],
            knowledge=knowledge,
            question=question,
            tools=selected_tools,
            request_token_budget=self.config.request_token_budget,
            max_completion_tokens=self.config.max_completion_tokens,
        )
        logging.info(
            "AI context request_id=%s estimated_tokens=%s budget=%s history=%s/%s knowledge=%s/%s truncated=%s",
            context.request_id,
            context_metrics["estimated_tokens"],
            self.config.request_token_budget,
            context_metrics["history_returned"],
            context_metrics["history_total"],
            context_metrics["knowledge_returned"],
            context_metrics["knowledge_total"],
            context_metrics["truncated"],
        )
        selected_tool_names = {
            schema["function"]["name"] for schema in selected_tools
        }
        chunks: list[str] = []
        try:
            if selected_tools:
                while rounds < self.config.max_tool_rounds:
                    messages, budget_metrics = fit_messages_to_budget(
                        messages,
                        tools=selected_tools,
                        request_token_budget=self.config.request_token_budget,
                        max_completion_tokens=self.config.max_completion_tokens,
                    )
                    logging.info(
                        "AI request budget request_id=%s phase=tool estimated_tokens=%s budget=%s removed=%s knowledge_removed=%s",
                        context.request_id,
                        budget_metrics["estimated_tokens"],
                        self.config.request_token_budget,
                        budget_metrics["history_messages_removed"],
                        budget_metrics["knowledge_removed"],
                    )
                    planning = await self.provider.complete(
                        messages,
                        tools=selected_tools,
                        tool_choice="auto",
                        request_id=context.request_id,
                    )
                    self._merge_usage(usage, planning.usage)
                    if not planning.tool_calls:
                        if planning.content:
                            chunks.append(planning.content)
                            yield AIStreamEvent("delta", {"content": planning.content})
                        break
                    rounds += 1
                    # A mensagem assistant contém os tool_calls e deve preceder
                    # exatamente os resultados role=tool correspondentes.
                    messages.append(planning.assistant_message)
                    for call in planning.tool_calls:
                        tools_called.append(call.name)
                        yield AIStreamEvent(
                            "status",
                            {"message": self.tools.status_label(call.name)},
                        )
                        tool_started = time.monotonic()
                        if call.name not in selected_tool_names:
                            result = {
                                "error": {
                                    "code": "ai_tool_not_selected",
                                    "message": "A IA tentou usar uma consulta que não foi disponibilizada.",
                                }
                            }
                        else:
                            try:
                                result = await asyncio.to_thread(
                                    self.tools.execute,
                                    call.name,
                                    call.arguments,
                                    context,
                                )
                                artifact = (
                                    result.get("data", {}).get("artifact")
                                    if isinstance(result, dict) else None
                                )
                                if isinstance(artifact, dict):
                                    artifacts.append(artifact)
                                    yield AIStreamEvent("artifact", artifact)
                            except AIToolError as exc:
                                result = {
                                    "error": {
                                        "code": exc.code,
                                        "message": exc.user_message,
                                    }
                                }
                        logging.info(
                            "AI tool request_id=%s conversation_id=%s user_id=%s tool=%s elapsed_ms=%s",
                            context.request_id,
                            conversation_id,
                            context.user_id,
                            call.name,
                            round((time.monotonic() - tool_started) * 1000),
                        )
                        messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": call.id,
                                "name": call.name,
                                "content": json.dumps(result, ensure_ascii=False, separators=(",", ":")),
                            }
                        )
                else:
                    limit_reached = True

            if not chunks:
                if limit_reached:
                    yield AIStreamEvent(
                        "status",
                        {"message": "Limite de consultas atingido; consolidando a resposta…"},
                    )
                else:
                    yield AIStreamEvent("status", {"message": "Preparando a resposta…"})

                if selected_tools:
                    messages.append(
                        {
                            "role": "system",
                            "content": FINAL_RESPONSE_INSTRUCTION,
                        }
                    )
                messages, budget_metrics = fit_messages_to_budget(
                    messages,
                    tools=[],
                    request_token_budget=self.config.request_token_budget,
                    max_completion_tokens=self.config.max_completion_tokens,
                )
                logging.info(
                    "AI request budget request_id=%s phase=final estimated_tokens=%s budget=%s removed=%s knowledge_removed=%s",
                    context.request_id,
                    budget_metrics["estimated_tokens"],
                    self.config.request_token_budget,
                    budget_metrics["history_messages_removed"],
                    budget_metrics["knowledge_removed"],
                )
                async for delta in self.provider.stream(
                    messages,
                    tools=[],
                    tool_choice="none",
                    request_id=context.request_id,
                ):
                    if not delta:
                        continue
                    chunks.append(delta)
                    yield AIStreamEvent("delta", {"content": delta})
            answer = "".join(chunks).strip()
            if not answer:
                raise AIServiceError(
                    "ai_empty_response",
                    "A Groq não produziu uma resposta válida. Tente novamente.",
                    retryable=True,
                )
            assistant_message = self.repository.adicionar_mensagem_ia(
                conversation_id,
                context.user_id,
                "assistant",
                answer,
                model=self.config.model,
                metadata={
                    "request_id": context.request_id,
                    "tool_rounds": rounds,
                    "tools": tools_called,
                    "tool_limit_reached": limit_reached,
                    "usage": usage,
                    "artifacts": artifacts,
                },
            )
            if assistant_message is None:
                raise AIConversationNotFoundError(
                    "ai_conversation_not_found",
                    "Conversa não encontrada.",
                )
            success = True
            yield AIStreamEvent(
                "done",
                {
                    "message": assistant_message,
                    "conversation_id": conversation_id,
                    "tool_rounds": rounds,
                    "artifacts": artifacts,
                },
            )
        except asyncio.CancelledError:
            logging.info(
                "AI request cancelled request_id=%s conversation_id=%s user_id=%s model=%s tools=%s",
                context.request_id,
                conversation_id,
                context.user_id,
                self.config.model,
                tools_called,
            )
            raise
        finally:
            logging.info(
                "AI request request_id=%s conversation_id=%s user_id=%s model=%s elapsed_ms=%s tools=%s success=%s usage=%s",
                context.request_id,
                conversation_id,
                context.user_id,
                self.config.model,
                round((time.monotonic() - started) * 1000),
                tools_called,
                success,
                usage,
            )
