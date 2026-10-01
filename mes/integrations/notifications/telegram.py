"""Aviso ao supervisor quando um item da outbox TOTVS para em ERROR.

Decisão do piloto (14/09/2026): a outbox já evita loop infinito em rejeição de
negócio (ex.: ``A680OPTOT Operacao ja totalizada``) — o item simplesmente fica
registrado como pendência. O que faltava era alguém saber na hora. Este módulo
só avisa; a resolução continua manual, feita pelo supervisor.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Callable

import httpx


DEFAULT_TIMEOUT_SECONDS = 10.0

# A Bot API exige o token no PATH da URL, e o httpx registra cada requisição
# ("HTTP Request: POST https://api.telegram.org/bot<TOKEN>/...") em INFO. Se o
# nível de log for elevado algum dia, o token iria parar em arquivo de log.
_TELEGRAM_TOKEN_IN_URL = re.compile(r"(api\.telegram\.org/bot)[^/\s\"']+")


class _TelegramTokenRedactor(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        if "api.telegram.org/bot" in message:
            record.msg = _TELEGRAM_TOKEN_IN_URL.sub(r"\1***", message)
            record.args = ()
        return True


def install_telegram_log_redaction() -> None:
    """Mascara o token do bot nos logs do httpx (idempotente)."""

    logger = logging.getLogger("httpx")
    if not any(isinstance(item, _TelegramTokenRedactor) for item in logger.filters):
        logger.addFilter(_TelegramTokenRedactor())


install_telegram_log_redaction()


def telegram_outbound_allowed(settings) -> bool:
    """Único predicado de saída: ``TELEGRAM_ENABLED`` liga/desliga todo envio.

    Vale para chamada do operador, parada/alertas, aviso do Corte e outbox
    TOTVS. Falha fechada: ``settings`` sem o atributo conta como desligado.
    Token e chat configurados continuam sendo checados por quem envia; esta
    função só responde se o canal de saída pode ser usado.
    """

    return bool(getattr(settings, "telegram_enabled", False))


TEST_MESSAGE_PREFIX = "[TESTE] "
_message_prefix = ""


def configure_message_prefix(environment) -> str:
    """Marca TODA mensagem enviada fora de produção com ``[TESTE] ``.

    Ponto único: um chat compartilhado entre TEST e REAL nunca mistura aviso
    de teste com aviso real. Chamada no startup com ``settings.environment``;
    ``None`` ou produção limpam o prefixo. Devolve o prefixo ativo.
    """

    global _message_prefix
    production = str(environment or "").strip().casefold() in {"production", "producao", "produção"}
    _message_prefix = "" if environment is None or production else TEST_MESSAGE_PREFIX
    return _message_prefix


def _prepare_outgoing_payload(method: str, payload: dict) -> dict:
    """Prefixo de ambiente e limite de 4096 caracteres, em um lugar só."""

    if method not in ("sendMessage", "editMessageText") or "text" not in payload:
        return payload
    from mes.services.telegram_presenter import fit_telegram_text

    text = str(payload["text"] or "")
    if _message_prefix and not text.startswith(_message_prefix):
        text = _message_prefix + text
    return {**payload, "text": fit_telegram_text(text)}


class TelegramPollingRejected(RuntimeError):
    """``getUpdates`` recusado de forma que insistir a cada ciclo não resolve.

    401: token inválido/revogado. 409: outro consumidor (outro processo, ou o
    mesmo bot em TEST e REAL) está lendo as atualizações — por isso TEST e REAL
    devem usar bots/tokens diferentes.
    """

    def __init__(self, status_code: int):
        self.status_code = status_code
        super().__init__(f"getUpdates recusado (HTTP {status_code})")


@dataclass(frozen=True)
class _Attempt:
    """Desfecho de UMA chamada à Bot API (nunca carrega o token)."""

    result: object | None = None
    error: str | None = None
    retryable: bool = False
    retry_after: float | None = None


def _retry_after_seconds(response: httpx.Response) -> float | None:
    try:
        value = (response.json().get("parameters") or {}).get("retry_after")
    except (ValueError, AttributeError):
        value = None
    if value is None:
        value = response.headers.get("Retry-After")
    try:
        return max(float(value), 0.0) if value is not None else None
    except (TypeError, ValueError):
        return None


def _telegram_attempt(
    *,
    bot_token: str,
    method: str,
    payload: dict,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> _Attempt:
    """Executa um método da Bot API e só aceita o ACK JSON ``ok=true``."""

    url = f"https://api.telegram.org/bot{bot_token}/{method}"
    payload = _prepare_outgoing_payload(method, payload)
    try:
        response = httpx.post(url, json=payload, timeout=timeout)
        if response.status_code >= 400:
            # Atualizar sem mudança visível já atingiu o estado desejado; não
            # envie uma segunda mensagem e não polua o chat nesse caso.
            if method == "editMessageText" and "message is not modified" in response.text.casefold():
                return _Attempt(result={})
            logging.warning(
                "%s do Telegram recusado (HTTP %s): %s",
                method,
                response.status_code,
                response.text[:300],
            )
            return _Attempt(
                error=f"HTTP {response.status_code}: {response.text[:160].strip()}",
                # 429 e 5xx são transitórios; os demais 4xx (chat inexistente,
                # bot bloqueado, HTML inválido) não melhoram com nova tentativa.
                retryable=response.status_code == 429 or response.status_code >= 500,
                retry_after=_retry_after_seconds(response) if response.status_code == 429 else None,
            )
        try:
            data = response.json()
        except ValueError:
            logging.warning("%s do Telegram sem ACK JSON válido.", method)
            return _Attempt(error="resposta sem ACK JSON válido")
        if data.get("ok") is not True:
            logging.warning("%s do Telegram sem ACK da Bot API: %s", method, str(data)[:300])
            return _Attempt(error="Bot API sem ACK ok=true")
        return _Attempt(result=data.get("result", True))
    except httpx.HTTPError as exc:
        logging.exception("Falha no método %s do Telegram.", method)
        # Só repete quando a requisição comprovadamente não chegou ao Telegram.
        # Timeout de leitura é ambíguo (a mensagem pode ter saído) e repetir
        # duplicaria o aviso.
        return _Attempt(
            error=f"falha de rede ({type(exc).__name__})",
            retryable=isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout)),
        )


def _telegram_request_result(
    *,
    bot_token: str,
    method: str,
    payload: dict,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> object | None:
    return _telegram_attempt(
        bot_token=bot_token, method=method, payload=payload, timeout=timeout
    ).result


def _telegram_request(
    *,
    bot_token: str,
    method: str,
    payload: dict,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> bool:
    return _telegram_request_result(
        bot_token=bot_token, method=method, payload=payload, timeout=timeout
    ) is not None


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


def send_telegram_message_with_id(
    *,
    bot_token: str,
    chat_id: str,
    text: str,
    parse_mode: str | None = None,
    reply_markup: dict | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> int | None:
    """Envia e devolve o ``message_id`` confirmado pela Bot API."""

    payload = {"chat_id": chat_id, "text": text}
    if parse_mode:
        payload["parse_mode"] = parse_mode
    if reply_markup is not None:
        payload["reply_markup"] = reply_markup
    result = _telegram_request_result(
        bot_token=bot_token, method="sendMessage", payload=payload, timeout=timeout
    )
    if not isinstance(result, dict) or result.get("message_id") is None:
        return None
    return int(result["message_id"])


@dataclass(frozen=True)
class TelegramSendResult:
    """Desfecho final de um envio com retry: ``ok`` ou o motivo da falha."""

    ok: bool
    error: str | None = None
    attempts: int = 1


# Espera máxima honrada de ``retry_after``: o envio roda em background e não
# deve segurar a thread por minutos. Acima disso, falha e registra o motivo.
MAX_RETRY_AFTER_SECONDS = 15.0
DEFAULT_SEND_ATTEMPTS = 3
_BACKOFF_SECONDS = (1.0, 2.0)


def send_telegram_message_checked(
    *,
    bot_token: str,
    chat_id: str,
    text: str,
    parse_mode: str | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    attempts: int = DEFAULT_SEND_ATTEMPTS,
    sleep: Callable[[float], None] = time.sleep,
) -> TelegramSendResult:
    """Envia com retry curto e devolve o desfecho final, com o motivo da falha.

    Repete só em falha transitória (conexão que não chegou ao Telegram, 5xx e
    429 respeitando ``retry_after``). Erro permanente (chat inexistente, bot
    bloqueado, HTML inválido) falha na hora. Nunca levanta e o motivo devolvido
    nunca contém o token.
    """

    payload = {"chat_id": chat_id, "text": text}
    if parse_mode:
        payload["parse_mode"] = parse_mode
    attempts = max(int(attempts), 1)
    last_error = "falha desconhecida"
    number = 0
    for number in range(1, attempts + 1):
        outcome = _telegram_attempt(
            bot_token=bot_token, method="sendMessage", payload=payload, timeout=timeout
        )
        if outcome.result is not None:
            return TelegramSendResult(ok=True, attempts=number)
        last_error = outcome.error or last_error
        if not outcome.retryable or number == attempts:
            break
        if outcome.retry_after is not None:
            if outcome.retry_after > MAX_RETRY_AFTER_SECONDS:
                last_error = f"{last_error} (retry_after={outcome.retry_after:g}s acima do limite)"
                break
            delay = outcome.retry_after
        else:
            delay = _BACKOFF_SECONDS[min(number - 1, len(_BACKOFF_SECONDS) - 1)]
        sleep(delay)
    return TelegramSendResult(ok=False, error=last_error[:300], attempts=number)


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
        if response.status_code in (401, 409):
            raise TelegramPollingRejected(response.status_code)
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


def format_chamada_message(chamada: dict, *, now: datetime | None = None) -> str:
    """Mensagem HTML do botão de chamada (operador ou gestão).

    Mesmo apresentador das demais mensagens automáticas: emoji, título em
    negrito e linhas rotuladas. Sempre enviada com ``parse_mode="HTML"``.
    """

    from mes.services.telegram_presenter import TelegramPresenter

    return TelegramPresenter().chamada(chamada, now=now or datetime.now())


def build_outbox_error_notifier(
    *, bot_token: str | None, chat_id: str | None, enabled: bool
) -> Callable[[dict], None] | None:
    """Fábrica usada pelo worker; ``None`` quando o Telegram não está configurado.

    Sem token/chat_id configurados, ou com ``enabled`` falso (resultado de
    ``telegram_outbound_allowed``), o comportamento é exatamente o de antes
    desta pendência: item fica em ERROR, visível só via outbox/observability.
    """

    if not enabled:
        return None
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
    "configure_message_prefix",
    "deliver_telegram_message",
    "edit_telegram_message",
    "fetch_telegram_updates",
    "format_chamada_message",
    "send_telegram_message",
    "send_telegram_message_checked",
    "send_telegram_message_with_id",
    "telegram_outbound_allowed",
    "TelegramPollingRejected",
    "TelegramSendResult",
]
