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


def _telegram_request(
    *,
    bot_token: str,
    method: str,
    payload: dict,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> bool:
    """Executa um método da Bot API e só aceita o ACK JSON ``ok=true``."""

    url = f"https://api.telegram.org/bot{bot_token}/{method}"
    try:
        response = httpx.post(url, json=payload, timeout=timeout)
        if response.status_code >= 400:
            # Atualizar sem mudança visível já atingiu o estado desejado; não
            # envie uma segunda mensagem e não polua o chat nesse caso.
            if method == "editMessageText" and "message is not modified" in response.text.casefold():
                return True
            logging.warning(
                "%s do Telegram recusado (HTTP %s): %s",
                method,
                response.status_code,
                response.text[:300],
            )
            return False
        try:
            data = response.json()
        except ValueError:
            logging.warning("%s do Telegram sem ACK JSON válido.", method)
            return False
        if data.get("ok") is not True:
            logging.warning("%s do Telegram sem ACK da Bot API: %s", method, str(data)[:300])
            return False
        return True
    except httpx.HTTPError:
        logging.exception("Falha no método %s do Telegram.", method)
        return False


def send_telegram_message(
    *,
    bot_token: str,
    chat_id: str,
    text: str,
    parse_mode: str | None = None,
    reply_markup: dict | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> bool:
    """Envia uma mensagem simples via Bot API do Telegram.

    Falha de rede ou configuração vira log, nunca exceção: quem chama decide o
    que fazer com o retorno (``True``/``False``) — por exemplo, persistir que o
    aviso não saiu, sem derrubar o fluxo que já registrou o fato original.
    """

    payload = {"chat_id": chat_id, "text": text}
    if parse_mode:
        payload["parse_mode"] = parse_mode
    if reply_markup is not None:
        payload["reply_markup"] = reply_markup
    return _telegram_request(
        bot_token=bot_token, method="sendMessage", payload=payload, timeout=timeout
    )


def edit_telegram_message(
    *,
    bot_token: str,
    chat_id: str,
    message_id: int,
    text: str,
    parse_mode: str | None = None,
    reply_markup: dict | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> bool:
    payload = {"chat_id": chat_id, "message_id": int(message_id), "text": text}
    if parse_mode:
        payload["parse_mode"] = parse_mode
    if reply_markup is not None:
        payload["reply_markup"] = reply_markup
    return _telegram_request(
        bot_token=bot_token, method="editMessageText", payload=payload, timeout=timeout
    )


def answer_telegram_callback_query(
    *,
    bot_token: str,
    callback_query_id: str,
    text: str | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> bool:
    payload = {"callback_query_id": callback_query_id}
    if text:
        payload["text"] = text
    return _telegram_request(
        bot_token=bot_token, method="answerCallbackQuery", payload=payload, timeout=timeout
    )


def deliver_telegram_message(
    *,
    bot_token: str,
    chat_id: str,
    text: str,
    message_id: int | None = None,
    parse_mode: str | None = None,
    reply_markup: dict | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> bool:
    """Edita navegação existente e usa ``sendMessage`` como fallback."""

    if message_id is not None and edit_telegram_message(
        bot_token=bot_token,
        chat_id=chat_id,
        message_id=message_id,
        text=text,
        parse_mode=parse_mode,
        reply_markup=reply_markup,
        timeout=timeout,
    ):
        return True
    return send_telegram_message(
        bot_token=bot_token,
        chat_id=chat_id,
        text=text,
        parse_mode=parse_mode,
        reply_markup=reply_markup,
        timeout=timeout,
    )


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
    from mes.services.telegram_presenter import TelegramPresenter

    return TelegramPresenter().totvs_outbox_error(item)


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
            bot_token=token,
            chat_id=chat,
            text=_format_outbox_error_message(item),
            parse_mode="HTML",
        )

    return _notify


__all__ = [
    "build_outbox_error_notifier",
    "answer_telegram_callback_query",
    "deliver_telegram_message",
    "edit_telegram_message",
    "fetch_telegram_updates",
    "send_telegram_message",
]
