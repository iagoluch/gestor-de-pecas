"""Worker de entrega da outbox TOTVS, desacoplado do request do operador.

Separação de responsabilidades da Etapa 6:

```text
ENQUEUE  (transação do operador)   -> Database._enfileirar_outbound_totvs_tx
DELIVERY (este worker)             -> reserva -> WSPCP -> ACK -> estado final
```

O worker nunca é chamado de dentro do fluxo HTTP da Tela do Operador. Ele
reserva um lote curto, fecha a transação de reserva, faz o POST fora de
qualquer transação PostgreSQL aberta e só então grava o resultado. Assim uma
chamada SOAP lenta não segura conexão nem lock do banco.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import logging
import os
import socket
import threading
from typing import Callable, Protocol

from mes.integrations.totvs.outbound_models import TotvsOutboundMessage
from mes.integrations.totvs.outbox import (
    DEFAULT_MAX_ATTEMPTS,
    DEFAULT_MAX_AUTHENTICATION_ATTEMPTS,
    DeliveryAttempt,
    DeliveryClass,
    OutboxStatus,
    classify_attempt,
)


class TotvsOutboxGateway(Protocol):
    """Transporte necessário ao worker: reportar, não decidir retry."""

    def send_result(self, message: TotvsOutboundMessage): ...


@dataclass
class OutboxWorkerCycle:
    """Resumo de um ciclo, usado por testes, CLI e log operacional."""

    reserved: int = 0
    sent: int = 0
    retried: int = 0
    failed: int = 0
    recovered: int = 0
    items: list = None

    def __post_init__(self):
        if self.items is None:
            self.items = []

    def as_dict(self) -> dict:
        return {
            "reservados": self.reserved,
            "enviados": self.sent,
            "reagendados": self.retried,
            "com_erro": self.failed,
            "recuperados": self.recovered,
        }


def default_worker_name() -> str:
    """Identidade legível do processo/thread que reservou o item."""

    return f"{socket.gethostname()}:{os.getpid()}:{threading.get_ident()}"


class TotvsOutboxWorker:
    """Entrega itens da outbox ao WSPCP e persiste o desfecho de cada tentativa."""

    def __init__(
        self,
        database,
        gateway: TotvsOutboxGateway | None = None,
        *,
        worker_name: str | None = None,
        batch_size: int = 10,
        lease_seconds: int = 120,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
        max_authentication_attempts: int = DEFAULT_MAX_AUTHENTICATION_ATTEMPTS,
        now_func=None,
        error_notifier: Callable[[dict], None] | None = None,
    ):
        self.database = database
        self.gateway = gateway
        self.worker_name = worker_name or default_worker_name()
        self.batch_size = max(1, int(batch_size))
        self.lease_seconds = max(5, int(lease_seconds))
        self.max_attempts = max(1, int(max_attempts))
        self.max_authentication_attempts = max(1, int(max_authentication_attempts))
        self._now = now_func or getattr(database, "_now", None)
        # Pendência 2 do piloto (14/09/2026): item que para em ERROR (ex.: OP já
        # totalizada no TOTVS) precisa de alguém olhando, não só ficar na outbox.
        # ``None`` mantém o comportamento anterior — sem Telegram configurado,
        # nada muda.
        self.error_notifier = error_notifier

    def _instant(self):
        if self._now is not None:
            return self._now()
        # O relógio canônico é o da fachada de persistência; este ramo só existe
        # para dublês de teste que não expõem ``_now``.
        return datetime.now().replace(microsecond=0)

    # ------------------------------------------------------------------
    def recover_abandoned(self) -> list:
        """Devolve à fila itens ``SENDING`` cujo worker morreu no meio do envio.

        A ``idempotency_key`` é preservada: o Protheus pode já ter processado a
        mensagem, e reenviá-la com a mesma chave é exatamente o comportamento
        desejado no transporte *at least once*.
        """

        return self.database.recuperar_envios_abandonados_totvs(now=self._instant())

    def _attempt_from_result(self, result) -> DeliveryAttempt:
        ack = getattr(result, "ack", None)
        http_status = getattr(result, "http_status", None)
        internal_id = None
        if ack is not None and ack.internal_ids:
            internal_id = str(ack.internal_ids[0][1])
        succeeded = bool(
            ack is not None
            and ack.accepted
            and (http_status is None or http_status < 400)
        )
        return DeliveryAttempt(
            succeeded=succeeded,
            http_status=http_status,
            ack_status=ack.status if ack is not None else None,
            already_processed=bool(ack is not None and ack.already_processed),
            internal_id=internal_id,
            transport_failure=getattr(result, "transport_failure", None),
            soap_fault=getattr(result, "soap_fault", None),
            error_code=getattr(result, "error_code", None),
            error_message=getattr(result, "error_message", None),
            raw_response=getattr(result, "raw_response", None),
        )

    def deliver(self, item: dict) -> dict:
        """Envia um item já reservado e grava o resultado da tentativa."""

        started_at = item.get("last_attempt_at") or self._instant()
        attempt_number = max(1, int(item.get("attempts") or 1))
        message = TotvsOutboundMessage(
            transaction=str(item["transaction"]),
            idempotency_key=str(item["idempotency_key"]),
            xml=str(item["payload_xml"]),
        )
        if self.gateway is None:
            attempt = DeliveryAttempt(
                transport_failure="gateway_nao_configurado",
                error_code="gateway_nao_configurado",
                error_message="Worker outbound sem gateway WSPCP configurado.",
            )
        else:
            try:
                result = self.gateway.send_result(message)
            except Exception as exc:  # transporte/configuração fora do contrato
                attempt = DeliveryAttempt(
                    transport_failure="falha_de_transporte",
                    error_code=getattr(exc, "code", "falha_de_transporte"),
                    error_message=str(exc),
                )
            else:
                attempt = self._attempt_from_result(result)
        decision = classify_attempt(
            attempt,
            attempts=attempt_number,
            max_attempts=int(item.get("max_attempts") or self.max_attempts),
            max_authentication_attempts=self.max_authentication_attempts,
        )
        return self.database.concluir_item_outbound_totvs(
            item["id"],
            status=decision.status,
            attempt_number=attempt_number,
            started_at=started_at,
            delivery_class=decision.delivery_class.value,
            http_status=attempt.http_status,
            ack_status=attempt.ack_status,
            error_code=decision.error_code,
            error_message=decision.error_message,
            internal_id=attempt.internal_id,
            worker=self.worker_name,
            now=self._instant(),
        )

    def run_once(self) -> OutboxWorkerCycle:
        """Um ciclo completo: recuperar, reservar, entregar e persistir."""

        cycle = OutboxWorkerCycle()
        cycle.recovered = len(self.recover_abandoned())
        reserved = self.database.reservar_lote_outbound_totvs(
            worker=self.worker_name,
            batch_size=self.batch_size,
            lease_seconds=self.lease_seconds,
            now=self._instant(),
        )
        cycle.reserved = len(reserved)
        for item in reserved:
            try:
                final = self.deliver(item)
            except Exception:
                # A reserva continua válida: o lease expira e o item volta para
                # RETRY com a mesma chave, em vez de ficar preso em SENDING.
                logging.exception(
                    "Falha inesperada ao entregar item %s da outbox TOTVS.", item.get("id")
                )
                continue
            if final is None:
                continue
            cycle.items.append(final)
            status = str(final.get("status"))
            if status == OutboxStatus.SENT.value:
                cycle.sent += 1
            elif status == OutboxStatus.RETRY.value:
                cycle.retried += 1
            elif status == OutboxStatus.ERROR.value:
                cycle.failed += 1
                self._notify_error(final)
        return cycle

    def _notify_error(self, item: dict) -> None:
        if self.error_notifier is None:
            return
        try:
            self.error_notifier(item)
        except Exception:
            # Aviso é best-effort: o item já está persistido como ERROR: uma
            # falha ao notificar não pode mascarar isso nem derrubar o ciclo.
            logging.exception(
                "Falha ao notificar item %s da outbox TOTVS em ERROR.", item.get("id")
            )


__all__ = [
    "DeliveryClass",
    "OutboxWorkerCycle",
    "TotvsOutboxGateway",
    "TotvsOutboxWorker",
    "default_worker_name",
]
