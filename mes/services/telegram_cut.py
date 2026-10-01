"""Atualização compacta do apontamento canônico de Corte no Telegram."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
import logging
import threading

from mes.integrations.notifications.telegram import (
    edit_telegram_message,
    send_telegram_message_with_id,
    telegram_outbound_allowed,
)
from mes.services.telegram_presenter import TelegramPresenter


LOGGER = logging.getLogger(__name__)


class _OrderedKeyLocks:
    """Exclusão mútua por chave, atendida na ordem de chegada (FIFO).

    ``threading.Lock`` não garante a ordem em que as threads acordam; com
    senha por chave, Iniciar e Finalizar quase simultâneos do mesmo plano são
    aplicados na ordem em que chegaram. Vale por processo: o aviso do Corte
    roda no mesmo processo do backend (``BackgroundTasks``).
    """

    def __init__(self):
        self._condition = threading.Condition()
        self._next_ticket: dict[tuple, int] = {}
        self._serving: dict[tuple, int] = {}

    @contextmanager
    def hold(self, key: tuple):
        with self._condition:
            ticket = self._next_ticket.get(key, 0)
            self._next_ticket[key] = ticket + 1
            self._condition.wait_for(lambda: self._serving.get(key, 0) == ticket)
        try:
            yield
        finally:
            with self._condition:
                self._serving[key] = ticket + 1
                if self._serving[key] == self._next_ticket[key]:
                    del self._serving[key]
                    del self._next_ticket[key]
                self._condition.notify_all()


# Lê message_id -> edita/envia -> grava é uma sequência: sem serializar, dois
# avisos do mesmo (chat, tarefa, máquina) duplicam a mensagem ou gravam o
# estado antigo por cima do novo.
_CUT_MESSAGE_LOCKS = _OrderedKeyLocks()


class TelegramCutPlanNotifier:
    def __init__(
        self,
        database,
        *,
        bot_token: str,
        chat_id: str,
        sender=send_telegram_message_with_id,
        editor=edit_telegram_message,
    ):
        self.db = database
        self.bot_token = str(bot_token).strip()
        self.chat_id = str(chat_id).strip()
        self.sender = sender
        self.editor = editor
        self.presenter = TelegramPresenter()

    def notify(self, item: dict, *, event: str) -> bool:
        task = str(item.get("codigo_tarefa") or "").strip()
        program = str(item.get("programa_atual") or item.get("programa") or "").strip()
        machine = str(item.get("maquina") or "").strip()
        if not task or not program or not machine:
            LOGGER.warning("Apontamento de Corte sem tarefa/plano/recurso; Telegram ignorado.")
            return False

        occurred_at = self._occurred_at(item, event)
        text = self.presenter.cut_plan_event(
            item=item, event=event, now=occurred_at
        )
        if text is None:
            return False

        key = (self.chat_id, task.casefold(), machine.casefold())
        with _CUT_MESSAGE_LOCKS.hold(key):
            return self._send_or_edit(task, program, machine, text)

    def _send_or_edit(self, task: str, program: str, machine: str, text: str) -> bool:
        previous = self.db.obter_mensagem_telegram_corte(
            self.chat_id, task, machine
        )
        message_id = int(previous["message_id"]) if previous else None
        if message_id is not None and self.editor(
            bot_token=self.bot_token,
            chat_id=self.chat_id,
            message_id=message_id,
            text=text,
            parse_mode="HTML",
        ):
            self.db.registrar_mensagem_telegram_corte(
                self.chat_id, task, machine, program, message_id
            )
            return True

        message_id = self.sender(
            bot_token=self.bot_token,
            chat_id=self.chat_id,
            text=text,
            parse_mode="HTML",
        )
        if message_id is None:
            return False
        self.db.registrar_mensagem_telegram_corte(
            self.chat_id, task, machine, program, message_id
        )
        return True

    @staticmethod
    def _occurred_at(item: dict, event: str) -> datetime:
        if event == "corte_finalizado" and isinstance(item.get("data_fim"), datetime):
            return item["data_fim"]
        active = next(
            (
                nesting for nesting in (item.get("nestings") or [])
                if nesting.get("status") == "Em processo"
                and isinstance(nesting.get("data_inicio"), datetime)
            ),
            None,
        )
        if active:
            return active["data_inicio"]
        return item.get("data_inicio") if isinstance(item.get("data_inicio"), datetime) else datetime.now()


def build_cut_plan_notifier(database, settings) -> TelegramCutPlanNotifier | None:
    destinations = {
        str(key).strip().casefold(): str(value).strip()
        for key, value in (getattr(settings, "telegram_sector_chat_ids", {}) or {}).items()
        if str(value).strip()
    }
    token = str(getattr(settings, "telegram_bot_token", "") or "").strip()
    chat_id = destinations.get("corte", "")
    if not telegram_outbound_allowed(settings) or not token or not chat_id:
        return None
    return TelegramCutPlanNotifier(
        database, bot_token=token, chat_id=chat_id
    )


def notify_cut_plan_in_background(database, settings, item: dict, *, event: str) -> bool:
    """Aviso do Corte para rodar fora do request (``BackgroundTasks``).

    Função síncrona de propósito: o Starlette a executa em thread, então um
    Telegram lento não segura o apontamento nem o loop do servidor. O fato
    industrial já foi persistido; qualquer falha vira log e ``False``.
    """

    try:
        notifier = build_cut_plan_notifier(database, settings)
        if notifier is None:
            return False
        return notifier.notify(item, event=event)
    except Exception:
        LOGGER.exception("Falha ao atualizar o apontamento de Corte no Telegram.")
        return False


__all__ = ["TelegramCutPlanNotifier", "build_cut_plan_notifier", "notify_cut_plan_in_background"]
