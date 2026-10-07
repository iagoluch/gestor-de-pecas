"""Teste manual opt-in do provedor de IA com uma única tool e banco PostgreSQL de teste.

Roda o mesmo cenário (tool call de get_factory_status → execução canônica →
resposta final) em um ou mais modelos do provedor configurado no .env
(GESTOR_AI_BASE_URL/GESTOR_AI_API_KEY) e imprime, por modelo, sucesso do tool
call, latência e tokens. A chave nunca é impressa.

    $env:GESTOR_AI_REAL_TEST = "true"
    .venv\\Scripts\\python.exe scripts\\verificar_ia_provedor_real.py --models nvidia/nemotron-3-super-120b-a12b,moonshotai/kimi-k3
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
import sys
import time
import uuid

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.database import Database
from app.database.config import load_postgres_config
from backend.ai.openai_compatible_provider import OpenAICompatibleProvider
from backend.api.config import WebSettings
from mes.ai.prompts import FINAL_RESPONSE_INSTRUCTION, build_system_prompt
from mes.contracts import AIProviderError, AIRequestContext
from mes.services.ai_tools import AIToolRegistry
from mes.services.frontend_facade import FrontendBackendFacade


QUESTION = "Como está a fábrica agora?"
TOOL_NAME = "get_factory_status"


def _enabled(value: str | None) -> bool:
    return str(value or "").strip().casefold() in {"1", "true", "yes", "sim", "on"}


def _tokens(usage: dict | None) -> str:
    usage = usage or {}
    return f"{usage.get('prompt_tokens')}/{usage.get('completion_tokens')}/{usage.get('total_tokens')}"


async def _run_model(model: str, settings: WebSettings, tools: AIToolRegistry, selected) -> None:
    request_id = f"manual-ia-{uuid.uuid4()}"
    provider = OpenAICompatibleProvider(
        api_key=settings.ai_api_key,
        base_url=settings.ai_base_url,
        model=model,
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
    print(f"== MODEL={model}")
    started = time.perf_counter()
    try:
        first = await provider.complete(messages, tools=selected, tool_choice="auto", request_id=request_id)
        first_ms = (time.perf_counter() - started) * 1000
        call = first.tool_calls[0] if len(first.tool_calls) == 1 else None
        arguments_ok = False
        if call is not None and call.name == TOOL_NAME:
            try:
                arguments_ok = isinstance(json.loads(call.arguments), dict)
            except json.JSONDecodeError:
                arguments_ok = False
        tool_ok = bool(call is not None and call.name == TOOL_NAME and arguments_ok)
        print(f"TOOL_CALL_OK={str(tool_ok).lower()}")
        print(f"FIRST_FINISH_REASON={first.finish_reason}")
        print(f"FIRST_LATENCY_MS={first_ms:.0f}")
        print(f"FIRST_TOKENS_PROMPT/COMPLETION/TOTAL={_tokens(first.usage)}")
        if not tool_ok:
            print("RESULT=failed (o modelo não gerou exatamente uma tool call válida)")
            return

        result = await asyncio.to_thread(
            tools.execute,
            call.name,
            call.arguments,
            AIRequestContext(user_id=0, management_access=True, request_id=request_id),
        )
        messages.append(first.assistant_message)
        messages.append({
            "role": "tool",
            "tool_call_id": call.id,
            "name": call.name,
            "content": json.dumps(result, ensure_ascii=False, separators=(",", ":")),
        })
        messages.append({"role": "system", "content": FINAL_RESPONSE_INSTRUCTION})
        second_started = time.perf_counter()
        final = await provider.complete(messages, tools=[], tool_choice="none", request_id=request_id)
        final_ms = (time.perf_counter() - second_started) * 1000
        text = str(final.content or "").strip()
        print(f"FINAL_LATENCY_MS={final_ms:.0f}")
        print(f"FINAL_TOKENS_PROMPT/COMPLETION/TOTAL={_tokens(final.usage)}")
        print(f"FINAL_FINISH_REASON={final.finish_reason}")
        print(f"TOTAL_LATENCY_MS={(time.perf_counter() - started) * 1000:.0f}")
        print(f"RESULT={'success' if text else 'failed (sem texto final)'}")
        print("FINAL_RESPONSE_BEGIN")
        print(text)
        print("FINAL_RESPONSE_END")
    except AIProviderError as exc:
        # Só código e detalhes técnicos sanitizados; nunca a chave.
        print(f"RESULT=failed ERROR_CODE={exc.code} RETRYABLE={str(bool(exc.retryable)).lower()}")
        print(f"ERROR_DETAILS={json.dumps(exc.technical_details or {}, ensure_ascii=False)}")
    finally:
        print(f"REQUEST_ID={request_id}")


async def _run(models: list[str], pause_seconds: float) -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if not _enabled(os.getenv("GESTOR_AI_REAL_TEST")):
        print("SKIP: defina GESTOR_AI_REAL_TEST=true para autorizar o consumo real do provedor de IA.")
        return

    settings = WebSettings.from_env()
    if not settings.ai_configured:
        raise RuntimeError("GESTOR_AI_API_KEY (ou o legado GROQ_API_KEY) não está configurada no ambiente local.")
    print(f"BASE_URL={settings.ai_base_url}")

    database = Database(config=load_postgres_config(testing=True))
    try:
        now_func = (
            (lambda: settings.simulation_reference_time)
            if settings.simulation_mode and settings.simulation_reference_time is not None
            else None
        )
        facade = FrontendBackendFacade(database, now_func=now_func, simulation_mode=settings.simulation_mode)
        tools = AIToolRegistry(facade, now_func=now_func, tool_result_max_chars=settings.ai_tool_result_max_chars)
        selected = tools.schemas_for_names([TOOL_NAME])
        if len(selected) != 1 or selected[0]["function"]["name"] != TOOL_NAME:
            raise AssertionError(f"O teste deve expor somente {TOOL_NAME}.")
        for index, model in enumerate(models):
            if index and pause_seconds > 0:
                await asyncio.sleep(pause_seconds)  # respeita o RPM do plano gratuito
            await _run_model(model, settings, tools, selected)
    finally:
        database.close()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--models",
        default="",
        help="IDs separados por vírgula; vazio usa o GESTOR_AI_MODEL/padrão do provedor.",
    )
    parser.add_argument("--pause-seconds", type=float, default=3.0)
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    requested = [item.strip() for item in args.models.split(",") if item.strip()]
    if not requested:
        requested = [WebSettings.from_env().ai_model]
    asyncio.run(_run(requested, args.pause_seconds))
