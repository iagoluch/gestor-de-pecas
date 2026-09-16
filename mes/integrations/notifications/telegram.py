"""Aviso ao supervisor quando um item da outbox TOTVS para em ERROR.

Decisão do piloto (14/09/2026): a outbox já evita loop infinito em rejeição de
negócio (ex.: ``A680OPTOT Operacao ja totalizada``) — o item simplesmente fica
registrado como pendência. O que faltava era alguém saber na hora. Este módulo
só avisa; a resolução continua manual, feita pelo supervisor.
"""

from __future__ import annotations

import logging
from typing import Callable

import httpx


DEFAULT_TIMEOUT_SECONDS = 10.0


def send_telegram_message(
    *, bot_token: str, chat_id: str, text: str, timeout: float = DEFAULT_TIMEOUT_SECONDS
) -> bool:
    """Envia uma mensagem simples via Bot API do Telegram.

    Falha de rede ou configuração vira log, nunca exceção: quem chama decide o
    que fazer com o retorno (``True``/``False``) — por exemplo, persistir que o
    aviso não saiu, sem derrubar o fluxo que já registrou o fato original.
    """

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    try:
        response = httpx.post(
            url,
            json={"chat_id": chat_id, "text": text},
            timeout=timeout,
        )
        if response.status_code >= 400:
            logging.warning(
                "Notificação Telegram recusada (HTTP %s): %s",
                response.status_code,
                response.text[:300],
            )
            return False
        return True
    except httpx.HTTPError:
        logging.exception("Falha ao enviar notificação Telegram.")
        return False


def fetch_telegram_updates(
    *, bot_token: str, offset: int | None = None, timeout: float = DEFAULT_TIMEOUT_SECONDS
) -> list[dict]:
    """Busca atualizações pendentes via ``getUpdates`` (long polling curto).

    Sem webhook configurado (não há URL pública fixa neste ambiente), o
    polling é o caminho simples e já comprovado manualmente com este bot.
    ``offset`` é o ``update_id`` do último processado + 1, exatamente como a
    Bot API espera para confirmar recebimento e não repetir a mesma mensagem.
    """

    url = f"https://api.telegram.org/bot{bot_token}/getUpdates"
    params: dict[str, int] = {"timeout": 0}
    if offset is not None:
        params["offset"] = int(offset)
    try:
        response = httpx.get(url, params=params, timeout=timeout)
        if response.status_code >= 400:
            logging.warning(
                "getUpdates do Telegram recusado (HTTP %s): %s",
                response.status_code,
                response.text[:300],
            )
            return []
        data = response.json()
        if not data.get("ok"):
            return []
        return list(data.get("result") or [])
    except httpx.HTTPError:
        logging.exception("Falha ao buscar atualizações do Telegram.")
        return []


def _format_outbox_error_message(item: dict) -> str:
    op = item.get("production_order") or "?"
    operacao = item.get("operation_code") or "-"
    codigo = item.get("error_code") or "erro_desconhecido"
    motivo = str(item.get("error_message") or "").strip() or "sem detalhe do TOTVS"
    return (
        "⚠️ Gestor de Peças — apontamento não aceito pelo TOTVS\n"
        f"OP: {op}\n"
        f"Operação: {operacao}\n"
        f"Motivo: {codigo} — {motivo}\n"
        "Ação necessária: verificar no TOTVS e decidir manualmente."
    )


def format_chamada_message(chamada: dict) -> str:
    """Mensagem do botão de chamada (operador ou gestão), enviada só ao Telegram."""

    solicitante = f"{chamada.get('solicitante_nome')} ({chamada.get('solicitante_nivel')})"
    cracha = str(chamada.get("solicitante_cracha") or "").strip()
    email = str(chamada.get("solicitante_email") or "").strip()
    if cracha:
        solicitante += f" — crachá {cracha}"
    if email:
        solicitante += f" — {email}"
    return (
        "📣 Chamada no Gestor de Peças\n"
        f"Para: {chamada.get('contato_nome')} ({chamada.get('contato_funcao')})\n"
        f"Motivo: {chamada.get('motivo')}\n"
        f"Comentário: {chamada.get('comentario')}\n"
        f"Solicitado por: {solicitante}"
    )


def build_outbox_error_notifier(
    *, bot_token: str | None, chat_id: str | None
) -> Callable[[dict], None] | None:
    """Fábrica usada pelo worker; ``None`` quando o Telegram não está configurado.

    Sem token/chat_id configurados, o comportamento é exatamente o de antes
    desta pendência: item fica em ERROR, visível só via outbox/observability.
    """

    token = str(bot_token or "").strip()
    chat = str(chat_id or "").strip()
    if not token or not chat:
        return None

    def _notify(item: dict) -> None:
        send_telegram_message(
            bot_token=token, chat_id=chat, text=_format_outbox_error_message(item)
        )

    return _notify


__all__ = [
    "build_outbox_error_notifier",
    "fetch_telegram_updates",
    "send_telegram_message",
]
