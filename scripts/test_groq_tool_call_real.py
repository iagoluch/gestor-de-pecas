"""Teste manual opt-in da Groq com uma única tool e banco PostgreSQL de teste."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import sys
import uuid

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.database import Database
from app.database.config import load_postgres_config
from backend.ai.groq_provider import GroqProvider
from backend.api.config import WebSettings
from mes.ai.prompts import FINAL_RESPONSE_INSTRUCTION, build_system_prompt
from mes.contracts import AIRequestContext
from mes.services.ai_tools import AIToolRegistry
from mes.services.frontend_facade import FrontendBackendFacade


QUESTION = "Como está a fábrica agora?"


def _enabled(value: str | None) -> bool:
    return str(value or "").strip().casefold() in {"1", "true", "yes", "sim", "on"}


async def _run() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if not _enabled(os.getenv("GESTOR_AI_REAL_TEST")):
        print("SKIP: defina GESTOR_AI_REAL_TEST=true para autorizar o consumo real da Groq.")
        return

    settings = WebSettings.from_env()
    if not settings.ai_configured:
        raise RuntimeError("GROQ_API_KEY não está configurada no ambiente local.")

    config = load_postgres_config(testing=True)
    database = Database(config=config)
    try:
        now_func = (
            (lambda: settings.simulation_reference_time)
            if settings.simulation_mode and settings.simulation_reference_time is not None
            else None
        )
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
        selected = tools.schemas_for_names(["get_factory_status"])
        if len(selected) != 1 or selected[0]["function"]["name"] != "get_factory_status":
            raise AssertionError("O teste deve expor somente get_factory_status.")

        request_id = f"manual-groq-{uuid.uuid4()}"
        provider = GroqProvider(
            api_key=settings.ai_api_key,
            model=settings.ai_model,
            reasoning_effort=settings.ai_reasoning_effort,
            temperature=settings.ai_temperature,
            max_completion_tokens=settings.ai_max_completion_tokens,
            request_token_budget=settings.ai_request_token_budget,
            timeout_seconds=settings.ai_timeout_seconds,
        )
        messages = [
            {"role": "system", "content": build_system_prompt()},
            {"role": "user", "content": QUESTION},
        ]
        first = await provider.complete(
            messages,
            tools=selected,
            tool_choice="auto",
            request_id=request_id,
        )
        if first.finish_reason != "tool_calls":
            raise AssertionError(f"finish_reason inesperado: {first.finish_reason!r}")
        if len(first.tool_calls) != 1:
            raise AssertionError("A Groq não retornou exatamente uma tool call.")
        call = first.tool_calls[0]
        if call.name != "get_factory_status":
            raise AssertionError(f"Tool inesperada: {call.name!r}")
        arguments = json.loads(call.arguments)
        if not isinstance(arguments, dict):
            raise AssertionError("Os arguments da tool não formam um objeto JSON.")

        result = await asyncio.to_thread(
            tools.execute,
            call.name,
            call.arguments,
            AIRequestContext(user_id=0, management_access=True, request_id=request_id),
        )
        messages.append(first.assistant_message)
        tool_content = json.dumps(result, ensure_ascii=False, separators=(",", ":"))
        tool_message = {
            "role": "tool",
            "tool_call_id": call.id,
            "name": call.name,
            "content": tool_content,
        }
        messages.append(tool_message)
        messages.append({"role": "system", "content": FINAL_RESPONSE_INSTRUCTION})
        final = await provider.complete(
            messages,
            tools=[],
            tool_choice="none",
            request_id=request_id,
        )
        if not str(final.content or "").strip():
            raise AssertionError("A segunda chamada não produziu texto final.")

        first_usage = first.usage or {}
        final_usage = final.usage or {}
        limits = result.get("limits") or {}
        print("FIRST_HTTP=200")
        print(f"FIRST_PROMPT_TOKENS={first_usage.get('prompt_tokens')}")
        print(f"FIRST_COMPLETION_TOKENS={first_usage.get('completion_tokens')}")
        print(f"FIRST_TOTAL_TOKENS={first_usage.get('total_tokens')}")
        print(f"FIRST_FINISH_REASON={first.finish_reason}")
        print(f"TOOL={call.name}")
        print("ARGUMENTS_JSON_VALID=true")
        print("BACKEND_TOOL_EXECUTED=true")
        print(f"TOOL_RAW_CHARS={limits.get('raw_chars')}")
        print(f"TOOL_SENT_CHARS={len(tool_content)}")
        print(f"TOOL_ITEMS={limits.get('items')}")
        print(f"TOOL_TRUNCATED={str(bool(limits.get('truncated'))).lower()}")
        print("ASSISTANT_THEN_TOOL=true")
        print(f"TOOL_CALL_ID_PRESERVED={tool_message['tool_call_id'] == call.id}")
        print("SECOND_HTTP=200")
        print(f"SECOND_PROMPT_TOKENS={final_usage.get('prompt_tokens')}")
        print(f"SECOND_COMPLETION_TOKENS={final_usage.get('completion_tokens')}")
        print(f"SECOND_TOTAL_TOKENS={final_usage.get('total_tokens')}")
        print(f"SECOND_FINISH_REASON={final.finish_reason}")
        print(f"FINAL_TEXT_PRESENT={bool(str(final.content or '').strip())}")
        print("FINAL_RESPONSE_BEGIN")
        print(str(final.content or "").strip())
        print("FINAL_RESPONSE_END")
        print(f"REQUEST_ID={request_id}")
    finally:
        database.close()


if __name__ == "__main__":
    asyncio.run(_run())
