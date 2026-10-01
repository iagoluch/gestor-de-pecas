"""Despachante dos alertas internos para o Telegram.

Consome ``alertas_internos`` com ``canal_previsto='telegram'`` e
``status_notificacao='PENDENTE'`` (gravados por ``InternalAlertService``) e os
entrega no chat do setor responsável ou, na falta dele, no chat da fábrica.

Política de entrega:

* só envia com o Telegram habilitado (``telegram_outbound_allowed``), token e
  um chat de destino; sem isso o alerta **fica PENDENTE** — nada é descartado
  por falta de configuração;
* sucesso -> ``ENVIADA``; falha -> continua ``PENDENTE`` com a tentativa
  registrada e espera crescente (60s até 15min) antes da próxima;
* ``DESCARTADA`` só quando o alerta deixou de valer: já resolvido
  (``resolvido_em``) ou mais antigo que ``max_age`` — não faz sentido avisar
  de madrugada um refugo de ontem só porque o chat foi configurado agora;
* um único processo despacha por vez (``LeaderLease``, no laço do ``main``).

O texto vem de ``TelegramPresenter.internal_alert``: mensagem humana, sem
códigos de sistema e sem exigir nenhuma ação do operador.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from mes.integrations.notifications.telegram import send_telegram_message_checked
from mes.services.andon import ANDON_PANEL_BY_SECTOR
from mes.services.telegram_presenter import TelegramPresenter

LOGGER = logging.getLogger(__name__)

DEFAULT_MAX_AGE = timedelta(hours=24)
DEFAULT_BATCH_SIZE = 20
_SCAN_FACTOR = 10  # janela lida = lote × fator
_RETRY_MIN_SECONDS = 60
_RETRY_MAX_SECONDS = 900


@dataclass(frozen=True)
class DispatchCycle:
    sent: int = 0
    discarded: int = 0
    failed: int = 0
    deferred: int = 0  # segue PENDENTE sem tentativa (sem chat ou em espera)
    skipped: str | None = None  # motivo de nem ter consultado a fila


class InternalAlertTelegramDispatcher:
    def __init__(
        self,
        db,
        *,
        bot_token: str,
        factory_chat_id: str = "",
        sector_chat_ids: dict[str, str] | None = None,
        outbound_allowed: bool = True,
        sender=send_telegram_message_checked,
        now_func=None,
        max_age: timedelta = DEFAULT_MAX_AGE,
        batch_size: int = DEFAULT_BATCH_SIZE,
    ):
        self.db = db
        self.bot_token = str(bot_token or "").strip()
        self.factory_chat_id = str(factory_chat_id or "").strip()
        self.sector_chat_ids = {
            str(key).strip().casefold(): str(value).strip()
            for key, value in (sector_chat_ids or {}).items()
            if str(value).strip()
        }
        self.outbound_allowed = bool(outbound_allowed)
        self._sender = sender
        self._now = now_func or (lambda: datetime.now().replace(microsecond=0))
        self.max_age = max_age
        self.batch_size = batch_size
        self._presenter = TelegramPresenter()

    # ------------------------------------------------------------------
    def chat_for(self, alert: dict) -> str | None:
        """Chat do setor responsável (painel do Andon); senão o da fábrica."""

        panel = ANDON_PANEL_BY_SECTOR.get(str(alert.get("tipo_setor") or "").strip().casefold())
        if panel:
            chat = self.sector_chat_ids.get(panel.casefold())
            if chat:
                return chat
        return self.factory_chat_id or None

    def run_once(self) -> DispatchCycle:
        if not self.outbound_allowed:
            return DispatchCycle(skipped="telegram desligado")
        if not self.bot_token:
            return DispatchCycle(skipped="sem token")
        if not self.factory_chat_id and not self.sector_chat_ids:
            return DispatchCycle(skipped="sem chat configurado")
        listar = getattr(self.db, "listar_alertas_pendentes_telegram", None)
        if not callable(listar):
            return DispatchCycle(skipped="banco sem fila de alertas")

        sent = discarded = failed = deferred = 0
        attempted = 0
        # Lê uma janela maior que o lote: alertas adiados (sem chat do setor ou
        # em espera de reenvio) ficam no início da fila e, se contassem no
        # lote, esconderiam para sempre os alertas novos atrás deles.
        for alert in listar(limite=self.batch_size * _SCAN_FACTOR):
            if attempted >= self.batch_size:
                break
            now = self._now()
            # Validade antes do destino: alerta velho é descartado mesmo sem
            # chat, senão um setor sem chat acumularia PENDENTE para sempre.
            reason = self._stale_reason(alert, now)
            if reason:
                self.db.descartar_alerta_interno(alert["id"], agora=now, motivo=reason)
                discarded += 1
                continue
            chat_id = self.chat_for(alert)
            if not chat_id:
                deferred += 1  # sem destino para este setor: fica PENDENTE
                continue
            if self._waiting_retry(alert, now):
                deferred += 1
                continue
            attempted += 1
            result = self._sender(
                bot_token=self.bot_token,
                chat_id=chat_id,
                text=self._presenter.internal_alert(alert, now=now),
                parse_mode="HTML",
            )
            if result.ok:
                self.db.marcar_alerta_enviado(alert["id"], agora=now)
                sent += 1
            else:
                self.db.registrar_tentativa_alerta_interno(
                    alert["id"], agora=now, erro=result.error or "falha de envio"
                )
                LOGGER.warning(
                    "Alerta interno %s não entregue ao Telegram (segue PENDENTE): %s",
                    alert.get("id"),
                    result.error,
                )
                failed += 1
        return DispatchCycle(sent=sent, discarded=discarded, failed=failed, deferred=deferred)

    # ------------------------------------------------------------------
    def _stale_reason(self, alert: dict, now: datetime) -> str | None:
        if alert.get("resolvido_em") is not None:
            return "alerta já resolvido"
        created = alert.get("criado_em")
        if isinstance(created, datetime) and now - created > self.max_age:
            return "alerta expirado antes da entrega"
        return None

    @staticmethod
    def _delivery_history(alert: dict) -> dict:
        try:
            data = json.loads(alert.get("detalhes") or "{}")
        except (TypeError, ValueError):
            return {}
        return (data.get("entrega_telegram") or {}) if isinstance(data, dict) else {}

    def _waiting_retry(self, alert: dict, now: datetime) -> bool:
        history = self._delivery_history(alert)
        attempts = int(history.get("tentativas") or 0)
        try:
            last = datetime.fromisoformat(history["ultima_tentativa"])
        except (KeyError, TypeError, ValueError):
            return False
        if attempts <= 0:
            return False
        wait = min(_RETRY_MAX_SECONDS, _RETRY_MIN_SECONDS * 2 ** (attempts - 1))
        return now - last < timedelta(seconds=wait)


__all__ = ["DispatchCycle", "InternalAlertTelegramDispatcher"]
