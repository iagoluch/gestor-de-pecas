"""Interface privada, somente leitura, do bot de fábrica no Telegram."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time as dt_time
import logging
import threading
import time as time_module

from mes.contracts import AnalyticsFilter
from mes.domain.industrial import EventCategory
from mes.services.frontend_facade import FrontendBackendFacade
from mes.services.telegram_digest import canonical_sectors_for_panel
from mes.services.telegram_intents import front_from_text, parse_telegram_intent
from mes.services.telegram_presenter import (
    FRONTS,
    TelegramPresenter,
    TelegramView,
    format_duration,
    format_percent,
)


LOGGER = logging.getLogger(__name__)

# Tentativas de /vincular sem crachá válido, por chat — sem este freio, o
# comando permite sondar números de crachá até acertar um vínculo alheio
# (achado B1 da auditoria de segurança de 2026-09-23, mesmo espírito do
# atraso de login em backend/api/routers/auth.py).
_LINK_ATTEMPT_LIMIT = 5
_LINK_ATTEMPT_WINDOW_SECONDS = 600
_link_failures: dict[str, list[float]] = {}
_link_failures_lock = threading.Lock()


@dataclass(frozen=True)
class TelegramBotReply:
    chat_id: str
    text: str
    reply_markup: dict | None = None
    parse_mode: str = "HTML"
    message_id: int | None = None
    callback_query_id: str | None = None


class TelegramFactoryBotService:
    """Roteia comandos, callbacks e intenções privadas às consultas existentes."""

    def __init__(self, db, *, now_func=None, simulation_mode=False):
        self.db = db
        self._now = now_func or datetime.now
        self.facade = FrontendBackendFacade(
            db, now_func=self._now, simulation_mode=simulation_mode
        )
        self.presenter = TelegramPresenter()
        self._commands = {
            "/start": self._view_home,
            "/menu": self._view_home,
            "/ajuda": self._view_help,
            "/help": self._view_help,
            "/vincular": self._view_link,
            "/meustatus": self._view_me,
            "/fabrica": self._view_factory,
            "/producao": self._view_production,
            "/paradas": self._view_stops,
            "/recursos": self._view_resources,
        }

    def handle_update(self, update: dict) -> TelegramBotReply | None:
        callback = update.get("callback_query")
        if callback:
            return self._handle_callback(callback)

        message = update.get("message") or update.get("channel_post") or {}
        chat = message.get("chat") or {}
        chat_type = str(chat.get("type") or "").strip().casefold()
        if chat_type != "private":
            if chat_type in {"group", "supergroup", "channel"}:
                self.db.registrar_chat_telegram_descoberto(
                    chat.get("id"), chat_type, chat.get("title")
                )
            return None
        text = str(message.get("text") or "").strip()
        chat_id = str(chat.get("id") or "").strip()
        if not text or not chat_id:
            return None

        command, _, rest = text.partition(" ")
        command = command.split("@", 1)[0].casefold()
        try:
            if command.startswith("/"):
                handler = self._commands.get(command)
                view = handler(chat_id, rest.strip()) if handler else self._view_help(chat_id)
            else:
                view = self._view_from_intent(chat_id, text)
        except Exception:
            LOGGER.exception("Falha ao atender mensagem privada do bot de fábrica.")
            view = self.presenter.unavailable(retry_callback="gp:home", now=self._now())
        return self._reply(chat_id, view)

    def _handle_callback(self, callback: dict) -> TelegramBotReply | None:
        message = callback.get("message") or {}
        chat = message.get("chat") or {}
        chat_id = str(chat.get("id") or "").strip()
        callback_id = str(callback.get("id") or "").strip() or None
        if str(chat.get("type") or "").strip().casefold() != "private" or not chat_id:
            return None
        data = str(callback.get("data") or "").strip()
        message_id = message.get("message_id")
        try:
            view = self._view_from_callback(chat_id, data)
        except Exception:
            LOGGER.exception("Falha ao atender callback %s do bot de fábrica.", data)
            view = self.presenter.unavailable(
                retry_callback=data if data.startswith("gp:") else "gp:home",
                now=self._now(),
            )
        return self._reply(
            chat_id,
            view,
            message_id=int(message_id) if message_id is not None else None,
            callback_query_id=callback_id,
        )

    @staticmethod
    def _reply(
        chat_id: str,
        view: TelegramView,
        *,
        message_id: int | None = None,
        callback_query_id: str | None = None,
    ) -> TelegramBotReply:
        return TelegramBotReply(
            chat_id=chat_id,
            text=view.text,
            reply_markup=view.reply_markup,
            message_id=message_id,
            callback_query_id=callback_query_id,
        )

    def _view_from_callback(self, chat_id: str, data: str) -> TelegramView:
        direct = {
            "gp:home": self._view_home,
            "gp:factory": self._view_factory,
            "gp:production": self._view_production,
            "gp:stops": self._view_stops,
            "gp:fronts": self._view_fronts,
            "gp:me": self._view_me,
            "gp:help": self._view_help,
            "gp:link": self._view_link,
        }
        if data in direct:
            return direct[data](chat_id)
        prefix, separator, front = data.rpartition(":")
        if separator and front in FRONTS:
            if prefix == "gp:front":
                return self._view_front(chat_id, front=front)
            if prefix == "gp:prod":
                return self._view_production(chat_id, front=front)
            if prefix == "gp:stops":
                return self._view_stops(chat_id, front=front)
            if prefix == "gp:res":
                return self._view_resources(chat_id, front=front)
        return self._view_help(chat_id)

    def _view_from_intent(self, chat_id: str, text: str) -> TelegramView:
        intent = parse_telegram_intent(text)
        if intent.name == "factory_status":
            return self._view_factory(chat_id)
        if intent.name == "production":
            return self._view_production(chat_id, front=intent.front)
        if intent.name == "stoppages":
            return self._view_stops(chat_id, front=intent.front)
        if intent.name == "resources":
            return self._view_resources(chat_id, front=intent.front)
        if intent.name == "front_overview" and intent.front:
            return self._view_front(chat_id, front=intent.front)
        if intent.name == "my_status":
            return self._view_me(chat_id)
        if intent.name == "link_badge":
            return self._view_link(chat_id)
        if intent.name == "help":
            return self._view_help(chat_id)
        return self._view_home(chat_id)

    def _period_today(self, *, sector: str | None = None) -> AnalyticsFilter:
        now = self._now()
        return AnalyticsFilter(
            inicio=datetime.combine(now.date(), dt_time.min), fim=now, setor=sector
        )

    def _operator(self, chat_id: str) -> dict | None:
        return self.db.buscar_operador_por_telegram(chat_id)

    def _snapshot(self) -> dict:
        return self.facade.andon(self._period_today())

    @staticmethod
    def _stopped(snapshot: dict, *, front: str | None = None) -> list[dict]:
        expected = FRONTS[front][1] if front else None
        rows = []
        for panel in snapshot.get("sectors") or ():
            if expected and panel.get("name") != expected:
                continue
            for resource in panel.get("resources") or ():
                state = resource.get("state") or {}
                if state.get("category") != "parada":
                    continue
                rows.append({
                    "name": resource.get("name") or resource.get("code"),
                    "reason": state.get("display_label") or state.get("reason"),
                    "duration_seconds": state.get("duration_seconds"),
                })
        return rows

    @staticmethod
    def _resources_for_front(snapshot: dict, front: str) -> list[dict]:
        expected = FRONTS[front][1]
        panel = next(
            (item for item in snapshot.get("sectors") or () if item.get("name") == expected),
            None,
        )
        return list((panel or {}).get("resources") or ())

    @staticmethod
    def _front_summary(snapshot: dict, front: str) -> dict:
        expected = FRONTS[front][1]
        panel = next(
            (item for item in snapshot.get("sectors") or () if item.get("name") == expected),
            None,
        )
        # O estado de cada recurso vem com a categoria física canônica
        # (``producao``/``parada``...), a mesma que o resumo do Andon traduz
        # para estas chaves em ``AndonService``.
        keys = {
            EventCategory.PRODUCTION.value: "production",
            EventCategory.DOWNTIME.value: "downtime",
            EventCategory.SETUP.value: "setup",
            EventCategory.REWORK.value: "rework",
        }
        counts = dict.fromkeys(keys.values(), 0)
        for resource in (panel or {}).get("resources") or ():
            key = keys.get((resource.get("state") or {}).get("category"))
            if key is not None:
                counts[key] += 1
        return counts

    def _production_data(self, front: str | None = None) -> dict:
        sectors = canonical_sectors_for_panel(FRONTS[front][1]) if front else (None,)
        good = scrap = rework = 0
        kpis = None
        for sector in sectors:
            filters = self._period_today(sector=sector)
            totals = self.facade.analytics.quality(filters).get("totals")
            if totals is None:
                raise ValueError("Resumo de quantidade indisponível.")
            good += int(totals.get("boa") or 0)
            scrap += int(totals.get("refugo") or 0)
            rework += int(totals.get("retrabalho") or 0)
            if len(sectors) == 1:
                kpis = self.facade.management.get_overview(filters).get("kpis") or {}
        return {"good": good, "scrap": scrap, "rework": rework, "kpis": kpis or {}}

    def _downtime_total(self, front: str | None = None) -> float:
        sectors = canonical_sectors_for_panel(FRONTS[front][1]) if front else (None,)
        return sum(
            float(self.facade.analytics.downtimes(self._period_today(sector=sector)).get("total_seconds") or 0)
            for sector in sectors
        )

    def _view_home(self, chat_id: str, _rest: str = "") -> TelegramView:
        operator = self._operator(chat_id)
        snapshot = self._snapshot()
        production = self._production_data()
        return self.presenter.menu(
            name=(operator or {}).get("nome"), linked=operator is not None,
            summary=snapshot.get("summary") or {}, good=production.get("good"),
            now=self._now(),
        )

    def _view_help(self, _chat_id: str, _rest: str = "") -> TelegramView:
        return self.presenter.help()

    def _view_link(self, chat_id: str, rest: str = "") -> TelegramView:
        badge = rest.strip()
        if not badge:
            return self.presenter.link_badge(now=self._now())
        if self._link_rate_limited(chat_id):
            return self.presenter.link_badge(
                now=self._now(),
                message="Muitas tentativas de vínculo. Tente novamente em alguns minutos.",
            )
        operator = self.db.vincular_telegram_operador(badge, chat_id)
        if operator is None:
            self._register_link_failure(chat_id)
            return self.presenter.link_badge(
                now=self._now(), message=f"Crachá {badge} não encontrado ou inativo."
            )
        self._clear_link_failures(chat_id)
        return self.presenter.link_badge(
            now=self._now(), success=True,
            message=(f"Pronto, {operator.get('nome')}! Este chat foi vinculado ao crachá "
                     f"{operator.get('cracha')}."),
        )

    @staticmethod
    def _link_rate_limited(chat_id: str) -> bool:
        now = time_module.monotonic()
        with _link_failures_lock:
            attempts = [t for t in _link_failures.get(chat_id, ()) if now - t <= _LINK_ATTEMPT_WINDOW_SECONDS]
            _link_failures[chat_id] = attempts
            return len(attempts) >= _LINK_ATTEMPT_LIMIT

    @staticmethod
    def _register_link_failure(chat_id: str) -> None:
        now = time_module.monotonic()
        with _link_failures_lock:
            attempts = [t for t in _link_failures.get(chat_id, ()) if now - t <= _LINK_ATTEMPT_WINDOW_SECONDS]
            attempts.append(now)
            _link_failures[chat_id] = attempts

    @staticmethod
    def _clear_link_failures(chat_id: str) -> None:
        with _link_failures_lock:
            _link_failures.pop(chat_id, None)

    def _view_me(self, chat_id: str, _rest: str = "") -> TelegramView:
        operator = self._operator(chat_id)
        participations = self.db.participacoes_ativas_por_cracha(operator["cracha"]) if operator else []
        return self.presenter.my_status(
            operator=operator, participations=participations, now=self._now()
        )

    def _view_factory(self, chat_id: str, _rest: str = "") -> TelegramView:
        if not self._operator(chat_id):
            return self.presenter.link_badge(now=self._now())
        snapshot = self._snapshot()
        return self.presenter.factory(
            summary=snapshot.get("summary") or {}, stopped=self._stopped(snapshot),
            now=self._now(),
        )

    def _view_production(self, chat_id: str, _rest: str = "", *, front: str | None = None) -> TelegramView:
        if not self._operator(chat_id):
            return self.presenter.link_badge(now=self._now())
        return self.presenter.production(
            front=front, data=self._production_data(front), now=self._now()
        )

    def _view_stops(self, chat_id: str, _rest: str = "", *, front: str | None = None) -> TelegramView:
        if not self._operator(chat_id):
            return self.presenter.link_badge(now=self._now())
        snapshot = self._snapshot()
        counts = {key: self._front_summary(snapshot, key)["downtime"] for key in FRONTS}
        counts["all"] = int((snapshot.get("summary") or {}).get("downtime") or 0)
        return self.presenter.stops(
            front=front, active=self._stopped(snapshot, front=front),
            total_seconds=self._downtime_total(front), counts=counts, now=self._now(),
        )

    def _view_fronts(self, _chat_id: str, _rest: str = "") -> TelegramView:
        return self.presenter.fronts()

    def _view_front(self, chat_id: str, *, front: str) -> TelegramView:
        if not self._operator(chat_id):
            return self.presenter.link_badge(now=self._now())
        snapshot = self._snapshot()
        return self.presenter.front(
            front=front, summary=self._front_summary(snapshot, front),
            good=self._production_data(front).get("good"), now=self._now(),
        )

    def _view_resources(self, chat_id: str, rest: str = "", *, front: str | None = None) -> TelegramView:
        if not self._operator(chat_id):
            return self.presenter.link_badge(now=self._now())
        front = front or front_from_text(rest)
        if not front:
            return self._view_fronts(chat_id)
        snapshot = self._snapshot()
        return self.presenter.resources(
            front=front, items=self._resources_for_front(snapshot, front), now=self._now(),
        )


_formatar_duracao = format_duration
_formatar_percentual = lambda metric: format_percent(metric) or "sem dado"


__all__ = ["TelegramBotReply", "TelegramFactoryBotService"]
