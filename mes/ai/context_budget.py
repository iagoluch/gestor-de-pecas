"""Orçamento conservador de contexto para chamadas à IA."""

from __future__ import annotations

import json
import math
import re
from typing import Any, Iterable

from mes.ai.prompts.system_prompt import BASE_SYSTEM_PROMPT, build_system_prompt


CONTEXT_REDUCTION_NOTE = (
    "Contexto reduzido pelo orçamento da IA. Não preencha lacunas por inferência; "
    "declare ausência de evidência quando necessário."
)


def estimate_tokens(value: Any) -> int:
    """Estimativa deliberadamente conservadora, sem depender de tokenizer externo."""

    if isinstance(value, str):
        serialized = value
    else:
        serialized = json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)
    return max(1, math.ceil(len(serialized.encode("utf-8")) / 3))


def estimate_request_tokens(
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    max_completion_tokens: int,
) -> int:
    request_context = {"messages": messages, "tools": tools}
    # Pequena reserva para campos do protocolo que não estão no histórico.
    return estimate_tokens(request_context) + int(max_completion_tokens) + 32


def _knowledge_relevance(item: dict[str, Any], question: str, position: int) -> tuple[int, int]:
    terms = {
        term
        for term in re.findall(r"[a-zA-ZÀ-ÿ0-9_-]{3,}", question.casefold())
    }
    content = str(item.get("conteudo") or "").casefold()
    return (-sum(term in content for term in terms), position)


def build_budgeted_context(
    *,
    history: Iterable[dict[str, Any]],
    knowledge: Iterable[dict[str, Any]],
    question: str,
    tools: list[dict[str, Any]],
    request_token_budget: int,
    max_completion_tokens: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Preserva prompt/pergunta, depois histórico recente e knowledge relevante."""

    history_items = [
        {"role": str(item.get("role") or ""), "content": str(item.get("content") or "")}
        for item in history
        if str(item.get("role") or "") in {"user", "assistant"}
    ]
    for index in range(len(history_items) - 1, -1, -1):
        if history_items[index]["role"] == "user" and history_items[index]["content"] == question:
            del history_items[index]
            break

    history_turns: list[list[dict[str, Any]]] = []
    for item in history_items:
        if item["role"] == "user":
            history_turns.append([item])
        elif history_turns:
            history_turns[-1].append(item)

    selected_history: list[dict[str, Any]] = []
    base_messages = [
        {"role": "system", "content": BASE_SYSTEM_PROMPT},
        {"role": "user", "content": question},
    ]
    for turn in reversed(history_turns):
        candidate_history = [*turn, *selected_history]
        candidate = [base_messages[0], *candidate_history, base_messages[1]]
        if estimate_request_tokens(candidate, tools, max_completion_tokens) <= request_token_budget:
            selected_history = candidate_history

    valid_knowledge = [
        item
        for item in knowledge
        if str(item.get("status_validacao") or "").casefold() == "validado"
        and str(item.get("conteudo") or "").strip()
    ]
    ranked_knowledge = sorted(
        enumerate(valid_knowledge),
        key=lambda pair: _knowledge_relevance(pair[1], question, pair[0]),
    )
    selected_knowledge: list[dict[str, Any]] = []
    for _position, item in ranked_knowledge:
        candidate_knowledge = [*selected_knowledge, item]
        candidate_prompt = build_system_prompt(candidate_knowledge)
        candidate = [
            {"role": "system", "content": candidate_prompt},
            *selected_history,
            base_messages[1],
        ]
        if estimate_request_tokens(candidate, tools, max_completion_tokens) <= request_token_budget:
            selected_knowledge = candidate_knowledge

    truncated = (
        len(selected_history) < len(history_items)
        or len(selected_knowledge) < len(valid_knowledge)
    )
    prompt = build_system_prompt(selected_knowledge)
    if truncated:
        candidate_prompt = f"{prompt}\n\n{CONTEXT_REDUCTION_NOTE}"
        candidate = [
            {"role": "system", "content": candidate_prompt},
            *selected_history,
            base_messages[1],
        ]
        if estimate_request_tokens(candidate, tools, max_completion_tokens) <= request_token_budget:
            prompt = candidate_prompt

    messages = [
        {"role": "system", "content": prompt},
        *selected_history,
        base_messages[1],
    ]
    return messages, {
        "history_total": len(history_items),
        "history_returned": len(selected_history),
        "knowledge_total": len(valid_knowledge),
        "knowledge_returned": len(selected_knowledge),
        "truncated": truncated,
        "estimated_tokens": estimate_request_tokens(messages, tools, max_completion_tokens),
    }


def fit_messages_to_budget(
    messages: list[dict[str, Any]],
    *,
    tools: list[dict[str, Any]],
    request_token_budget: int,
    max_completion_tokens: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Remove somente contexto antigo; preserva pergunta e ciclo assistant/tool atual."""

    fitted = [dict(item) for item in messages]
    before = estimate_request_tokens(fitted, tools, max_completion_tokens)
    last_user = max(
        (index for index, item in enumerate(fitted) if item.get("role") == "user"),
        default=0,
    )
    removed = 0
    while (
        estimate_request_tokens(fitted, tools, max_completion_tokens) > request_token_budget
        and last_user > 1
    ):
        # Remove o turno mais antigo inteiro. Apagar apenas a pergunta ou a
        # resposta deixava mensagens assistente órfãs e consumia contexto sem
        # significado para o provider.
        end = next(
            (
                index for index in range(2, last_user + 1)
                if fitted[index].get("role") == "user"
            ),
            last_user,
        )
        removed_now = max(1, end - 1)
        del fitted[1:end]
        last_user -= removed_now
        removed += removed_now

    knowledge_removed = False
    if estimate_request_tokens(fitted, tools, max_completion_tokens) > request_token_budget:
        system = str(fitted[0].get("content") or "") if fitted else ""
        if system != BASE_SYSTEM_PROMPT:
            fitted[0] = {
                "role": "system",
                "content": f"{BASE_SYSTEM_PROMPT}\n\n{CONTEXT_REDUCTION_NOTE}",
            }
            knowledge_removed = True

    after = estimate_request_tokens(fitted, tools, max_completion_tokens)
    return fitted, {
        "before_tokens": before,
        "estimated_tokens": after,
        "history_messages_removed": removed,
        "knowledge_removed": knowledge_removed,
        "within_budget": after <= request_token_budget,
    }
