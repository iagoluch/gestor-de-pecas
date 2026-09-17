"""Atualização compacta do apontamento canônico de Corte no Telegram."""

from __future__ import annotations

from datetime import datetime
import logging

from mes.integrations.notifications.telegram import (
    edit_telegram_message,
    send_telegram_message_with_id,
)
from mes.services.telegram_presenter import TelegramPresenter


LOGGER = logging.getLogger(__name__)


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
    if not getattr(settings, "telegram_enabled", False) or not token or not chat_id:
        return None
    return TelegramCutPlanNotifier(
        database, bot_token=token, chat_id=chat_id
    )


__all__ = ["TelegramCutPlanNotifier", "build_cut_plan_notifier"]
