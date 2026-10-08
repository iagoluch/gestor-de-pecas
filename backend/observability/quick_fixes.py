"""Ações rápidas do Dev Observatory.

Duas ferramentas, ambas deliberadamente estreitas:

* **encerrar sessão do PostgreSQL** — ``pg_terminate_backend`` sobre um ``pid``
  que o próprio ``pg_stat_activity`` confirma ser do banco observado. Não é
  escrita de dado industrial; só roda no ambiente TESTE (a rota recusa o resto).
* **diagnóstico por IA** — monta um contexto curto e já sanitizado de um evento
  ou relatório e pede uma análise ao provedor de IA já configurado na API
  (NVIDIA Nemotron). Sem tools: o modelo só lê o texto que recebe e responde
  texto. Nada que ele diga é executado.
"""

from __future__ import annotations

import json
import re
from typing import Any

from backend.observability.classification import sanitize

EVENT_TRACEBACK_CHARS = 3_500
EVENT_DETAILS_CHARS = 1_200
REPORT_CHARS = 7_000

SYSTEM_PROMPT = (
    "Você é um engenheiro sênior de manutenção do Gestor de Peças "
    "(FastAPI + PostgreSQL + React, MES industrial). Recebe uma ocorrência já "
    "sanitizada e responde em português do Brasil, direto e curto, neste formato:\n"
    "1. Causa provável (uma frase)\n"
    "2. Onde olhar (arquivo/função/tabela, só se aparecer na evidência)\n"
    "3. Correção sugerida (passos curtos)\n"
    "4. Como validar\n"
    "Marque como [Provável] ou [Chutando] o que não estiver na evidência. "
    "Se faltar dado, diga qual. Não invente nomes de arquivo."
)

# Segredos que sobrevivem ao ``sanitize`` por estarem dentro de texto livre
# (mensagem de exceção, linha de traceback).
_INLINE_SECRET = re.compile(
    r"(?i)\b(bearer\s+|api[_-]?key\s*[=:]\s*|password\s*[=:]\s*|senha\s*[=:]\s*|"
    r"token\s*[=:]\s*|secret\s*[=:]\s*)(\S+)"
)


def scrub(text: Any) -> str:
    return _INLINE_SECRET.sub(lambda match: f"{match.group(1)}<omitido>", str(text or ""))


def event_context(event: dict) -> str:
    """Texto de uma ocorrência, sem usuário/papel e sem segredos."""

    details = json.dumps(sanitize(event.get("details") or {}), ensure_ascii=False, default=str)
    traceback_text = str(event.get("traceback") or "")[-EVENT_TRACEBACK_CHARS:]
    lines = [
        f"Requisição: {event.get('method')} {event.get('path')} (rota {event.get('route')})",
        f"Status: {event.get('status')} · classificação {event.get('classification')} · "
        f"latência {event.get('latency_ms')} ms",
        f"Código de erro: {event.get('error_code')}",
        f"Mensagem: {event.get('error_message')}",
        f"Exceção: {event.get('exception')}",
        f"Detalhes: {details[:EVENT_DETAILS_CHARS]}",
    ]
    if traceback_text:
        lines.append("Traceback (final):\n" + traceback_text)
    return scrub("\n".join(lines))


def report_context(markdown: str) -> str:
    return scrub(markdown[:REPORT_CHARS])


def build_messages(context: str, question: str | None) -> list[dict[str, str]]:
    ask = (question or "").strip() or "Explique o que aconteceu e como corrigir."
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"Pergunta: {ask}\n\n--- EVIDÊNCIA ---\n{context}"},
    ]


def terminate_backend(database, pid: int) -> dict:
    """Encerra uma sessão do banco observado, nunca a própria conexão do coletor."""

    with database.connection() as connection, connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT pg_terminate_backend(pid) AS terminated, state,
                   LEFT(REGEXP_REPLACE(query, '\\s+', ' ', 'g'), 200) AS query
            FROM pg_stat_activity
            WHERE pid = %s AND datname = current_database() AND pid <> pg_backend_pid()
            """,
            (pid,),
        )
        row = cursor.fetchone()
        connection.commit()
    if not row:
        return {"found": False, "terminated": False, "pid": pid}
    row = dict(row)
    return {
        "found": True,
        "terminated": bool(row.get("terminated")),
        "pid": pid,
        "state": row.get("state"),
        "query": row.get("query"),
    }


# ---------------------------------------------------------------------------
# Chat com a IA (conversa livre sobre erros, com a evidência já sanitizada)
# ---------------------------------------------------------------------------
CHAT_MAX_TURNS = 10
CHAT_TURN_CHARS = 1_500
SNAPSHOT_EVENTS = 8

CHAT_SYSTEM_PROMPT = (
    "Você é um engenheiro sênior de manutenção do Gestor de Peças (FastAPI + "
    "PostgreSQL + React, MES industrial) conversando com o desenvolvedor dentro do "
    "Dev Observatory. Responda em português do Brasil, direto e curto. Use só a "
    "evidência abaixo e a conversa; se faltar dado, diga qual dado falta e onde "
    "olhar no observatório. Marque como [Provável] ou [Chutando] o que não estiver "
    "na evidência. Não invente nomes de arquivo. Você só conversa: não executa "
    "nada; ações (encerrar sessão, gerar relatório) o desenvolvedor faz na tela."
)


def snapshot_context(summary: dict, events: list[dict]) -> str:
    """Retrato curto do que o observatório viu: contagens e últimas ocorrências."""

    lines = [
        f"Requisições: {summary.get('requests')} · defeitos: {summary.get('defects')} · "
        f"bloqueios esperados: {summary.get('expected_blocks')}",
        f"Classificações: {json.dumps(summary.get('classifications') or {}, ensure_ascii=False)}",
        f"Códigos mais frequentes: {json.dumps(summary.get('top_codes') or [], ensure_ascii=False, default=str)[:400]}",
    ]
    recent = [e for e in events if e.get("classification") not in {"OK", None}][:SNAPSHOT_EVENTS]
    if recent:
        lines.append("Últimas ocorrências não-OK:")
        for event in recent:
            lines.append(
                f"- #{event.get('sequence')} {event.get('timestamp')} {event.get('method')} "
                f"{event.get('route') or event.get('path')} → {event.get('status')} "
                f"{event.get('classification')} {event.get('error_code') or ''} "
                f"{str(event.get('error_message') or '')[:160]}"
            )
    return scrub("\n".join(lines))


def build_chat_messages(
    turns: list[dict], evidence: list[str], snapshot: str | None
) -> list[dict[str, str]]:
    """System prompt + evidência anexada + as últimas falas (já limitadas)."""

    parts = [CHAT_SYSTEM_PROMPT]
    if snapshot:
        parts.append("--- ESTADO ATUAL DO OBSERVATÓRIO ---\n" + snapshot)
    for index, text in enumerate(evidence, start=1):
        parts.append(f"--- EVIDÊNCIA ANEXADA {index} ---\n{text}")
    messages = [{"role": "system", "content": "\n\n".join(parts)}]
    for turn in turns[-CHAT_MAX_TURNS:]:
        messages.append({"role": turn["role"], "content": scrub(turn["content"])[:CHAT_TURN_CHARS]})
    return messages
