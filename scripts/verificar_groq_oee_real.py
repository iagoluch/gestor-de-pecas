"""Teste manual opt-in das perguntas reais de OEE, sem entrar na suíte automática."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
import sys
import uuid
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.database import Database
from app.database.config import load_postgres_config
from backend.ai.groq_provider import GroqProvider
from backend.api.config import WebSettings
from mes.contracts import AIRequestContext, AIServiceConfig, AIServiceError
from mes.services.ai_service import AIService
from mes.services.ai_tools import AIToolRegistry
from mes.services.frontend_facade import FrontendBackendFacade
from scripts.run_simulacao_residencia import configure_environment


QUESTIONS = (
    "Qual é o OEE da fábrica?",
    "Por que o OEE está nesse valor?",
    "Como estão Disponibilidade, Performance e FTT?",
    "Qual o OEE do Corte?",
)


def _enabled(value: str | None) -> bool:
    return str(value or "").strip().casefold() in {"1", "true", "yes", "sim", "on"}


class _MemoryAIRepository:
    """Repositório efêmero para testar exatamente o AIService sem gravar no banco."""

    def __init__(self):
        self._title = "Nova conversa"
        self._messages: list[dict[str, Any]] = []
        self._next_message_id = 1

    def criar_conversa_ia(self, user_id: int, title: str) -> dict[str, Any]:
        self._title = title
        return self.obter_conversa_ia(1, user_id)

    def listar_conversas_ia(self, user_id: int, *, limit: int = 100) -> list[dict[str, Any]]:
        return [self.obter_conversa_ia(1, user_id)]

    def obter_conversa_ia(
        self,
        conversation_id: int,
        user_id: int,
        *,
        message_limit: int | None = None,
    ) -> dict[str, Any] | None:
        if conversation_id != 1:
            return None
        messages = self._messages
        if message_limit is not None:
            messages = messages[-message_limit:]
        return {
            "id": 1,
            "user_id": user_id,
            "title": self._title,
            "messages": [dict(message) for message in messages],
        }

    def atualizar_titulo_conversa_ia(
        self,
        conversation_id: int,
        user_id: int,
        title: str,
    ) -> dict[str, Any] | None:
        if conversation_id != 1:
            return None
        self._title = title
        return self.obter_conversa_ia(conversation_id, user_id)

    def excluir_conversa_ia(self, conversation_id: int, user_id: int) -> bool:
        return conversation_id == 1

    def adicionar_mensagem_ia(
        self,
        conversation_id: int,
        user_id: int,
        role: str,
        content: str,
        *,
        model: str | None = None,
        metadata: dict | None = None,
    ) -> dict[str, Any] | None:
        if conversation_id != 1:
            return None
        message = {
            "id": self._next_message_id,
            "conversation_id": conversation_id,
            "role": role,
            "content": content,
            "model": model,
            "metadata": dict(metadata or {}),
        }
        self._next_message_id += 1
        self._messages.append(message)
        return dict(message)

    def listar_conhecimento_ia_validado(self, *, limit: int = 100) -> list[dict[str, Any]]:
        return []


async def _run(index: int) -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if not _enabled(os.getenv("GESTOR_AI_REAL_TEST")):
        print("SKIP: defina GESTOR_AI_REAL_TEST=true para autorizar o consumo real da Groq.")
        return
    if not 1 <= index <= len(QUESTIONS):
        raise ValueError(f"question-index deve estar entre 1 e {len(QUESTIONS)}.")

    configure_environment()
    settings = WebSettings.from_env()
    if not settings.ai_configured:
        raise RuntimeError("GROQ_API_KEY não está configurada no ambiente local.")

    question = QUESTIONS[index - 1]
    now_func = (
        (lambda: settings.simulation_reference_time)
        if settings.simulation_mode and settings.simulation_reference_time is not None
        else None
    )
    database = Database(config=load_postgres_config(testing=True))
    try:
        facade = FrontendBackendFacade(
            database,
            now_func=now_func,
            simulation_mode=settings.simulation_mode,
        )
        tools = AIToolRegistry(
            facade,
            now_func=now_func,
            tool_result_max_chars=settings.ai_tool_result_max_chars,
        )
        selected = tools.select_schemas(question)
        selected_names = [schema["function"]["name"] for schema in selected]
        provider = GroqProvider(
            api_key=settings.ai_api_key,
            model=settings.ai_model,
            reasoning_effort=settings.ai_reasoning_effort,
            temperature=settings.ai_temperature,
            max_completion_tokens=settings.ai_max_completion_tokens,
            request_token_budget=settings.ai_request_token_budget,
            timeout_seconds=settings.ai_timeout_seconds,
        )
        repository = _MemoryAIRepository()
        service = AIService(
            repository,
            provider,
            tools,
            AIServiceConfig(
                enabled=settings.ai_enabled,
                configured=settings.ai_configured and provider.configured,
                model=settings.ai_model,
                max_tool_rounds=settings.ai_max_tool_rounds,
                max_history_messages=settings.ai_max_history_messages,
                request_token_budget=settings.ai_request_token_budget,
                max_completion_tokens=settings.ai_max_completion_tokens,
            ),
        )
        request_id = f"manual-oee-{index}-{uuid.uuid4()}"
        context = AIRequestContext(user_id=0, management_access=True, request_id=request_id)
        chunks: list[str] = []
        done: dict[str, Any] | None = None
        print(f"QUESTION_INDEX={index}")
        print(f"QUESTION={question}")
        print(f"SELECTED_TOOLS={','.join(selected_names)}")
        try:
            async for event in service.stream_message(1, question, context):
                if event.event == "delta":
                    chunks.append(str(event.data.get("content") or ""))
                elif event.event == "done":
                    done = event.data
        except AIServiceError as exc:
            print("RESULT=failed")
            print(f"ERROR_CODE={exc.code}")
            print(f"RETRYABLE={str(bool(exc.retryable)).lower()}")
            print(f"REQUEST_ID={request_id}")
            return

        if done is None:
            raise AssertionError("O AIService não emitiu o evento final.")
        message = done.get("message") or {}
        answer = str(message.get("content") or "".join(chunks)).strip()
        metadata = message.get("metadata") or {}
        print("RESULT=success")
        print(f"TOOL_ROUNDS={metadata.get('tool_rounds', done.get('tool_rounds', 0))}")
        print(f"TOOLS_CALLED={','.join(metadata.get('tools') or [])}")
        print(f"PLANNING_USAGE={json.dumps(metadata.get('usage') or {}, ensure_ascii=False, sort_keys=True)}")
        print("FINAL_RESPONSE_BEGIN")
        print(answer)
        print("FINAL_RESPONSE_END")
        print(f"REQUEST_ID={request_id}")
    finally:
        database.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--question-index", type=int, required=True)
    args = parser.parse_args()
    asyncio.run(_run(args.question_index))
