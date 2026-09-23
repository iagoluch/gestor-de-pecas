"""Entrega controlada de relatórios; o artefato local permanece a fonte."""

from __future__ import annotations

import asyncio
from datetime import datetime
import logging
from typing import Any

from mes.contracts.messaging import MessagingError


LOGGER = logging.getLogger(__name__)


class ReportMessagingService:
    def __init__(
        self,
        repository,
        report_service,
        *,
        provider=None,
        enabled: bool = False,
        configured: bool = False,
        now_func=None,
    ):
        self.repository = repository
        self.report_service = report_service
        self.provider = provider
        self.enabled = bool(enabled)
        self.configured = bool(configured)
        self._now = now_func or datetime.now

    @staticmethod
    def _view(delivery: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": int(delivery["id"]),
            "report_id": str(delivery["report_id"]),
            "destination_id": int(delivery["destination_id"]),
            "status": str(delivery["status"]),
            "attempt": int(delivery.get("attempt") or 0),
            "error_code": delivery.get("error_code"),
            "requested_at": delivery.get("requested_at"),
            "completed_at": delivery.get("completed_at"),
        }

    async def send_report(
        self,
        report_id: str,
        *,
        user_id: int,
        destination_id: int,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        if not self.enabled:
            raise MessagingError(
                "messaging_disabled",
                "O envio de relatórios está desativado.",
                status_code=409,
            )
        if not self.configured or self.provider is None:
            raise MessagingError(
                "messaging_not_configured",
                "O envio de relatórios ainda não está configurado.",
                status_code=503,
            )

        record, path = await asyncio.to_thread(
            self.report_service.get, str(report_id), user_id=int(user_id)
        )
        destination = await asyncio.to_thread(
            self.repository.obter_destino_mensagem,
            int(destination_id), int(user_id), provider="telegram",
        )
        if not destination:
            raise MessagingError(
                "messaging_destination_not_found",
                "Destino não encontrado.",
                status_code=404,
            )

        key = str(idempotency_key or f"report:{report_id}:destination:{destination_id}")
        existing = await asyncio.to_thread(
            self.repository.obter_entrega_relatorio_por_idempotencia, key
        )
        if existing and existing.get("status") == "enviado":
            return self._view(existing)
        if int((existing or {}).get("attempt") or 0) >= 10:
            raise MessagingError(
                "messaging_retry_limit",
                "O limite de tentativas de envio foi atingido. O arquivo continua disponível para download.",
                status_code=409,
            )
        attempt = int((existing or {}).get("attempt") or 0) + 1
        requested_at = self._now().replace(microsecond=0)
        delivery = await asyncio.to_thread(
            self.repository.registrar_entrega_relatorio,
            report_id=str(report_id),
            requested_by=int(user_id),
            destination_id=int(destination_id),
            status="solicitado",
            attempt=attempt,
            error_code=None,
            requested_at=requested_at,
            completed_at=None,
            idempotency_key=key,
        )
        try:
            await self.provider.send_document(
                destination_ref=str(destination["destination_ref"]),
                path=path,
                filename=str(record["filename"]),
                caption=(
                    f"Gestor de Peças — relatório {record['report_type']} "
                    f"({record['period_start']:%d/%m/%Y} a {record['period_end']:%d/%m/%Y})"
                ),
            )
        except MessagingError as exc:
            delivery = await asyncio.to_thread(
                self.repository.registrar_entrega_relatorio,
                report_id=str(report_id),
                requested_by=int(user_id),
                destination_id=int(destination_id),
                status="falhou",
                attempt=attempt,
                error_code=exc.code,
                requested_at=requested_at,
                completed_at=self._now().replace(microsecond=0),
                idempotency_key=key,
            )
            LOGGER.warning(
                "Report delivery failed report_id=%s user_id=%s destination_id=%s code=%s retryable=%s",
                report_id, user_id, destination_id, exc.code, exc.retryable,
            )
            raise
        except Exception as exc:
            delivery = await asyncio.to_thread(
                self.repository.registrar_entrega_relatorio,
                report_id=str(report_id),
                requested_by=int(user_id),
                destination_id=int(destination_id),
                status="falhou",
                attempt=attempt,
                error_code="messaging_provider_error",
                requested_at=requested_at,
                completed_at=self._now().replace(microsecond=0),
                idempotency_key=key,
            )
            LOGGER.exception(
                "Unexpected report delivery failure report_id=%s user_id=%s destination_id=%s",
                report_id, user_id, destination_id,
            )
            raise MessagingError(
                "messaging_provider_error",
                "Não foi possível enviar o relatório. O arquivo continua disponível para download.",
                status_code=502,
                retryable=True,
            ) from exc

        delivery = await asyncio.to_thread(
            self.repository.registrar_entrega_relatorio,
            report_id=str(report_id),
            requested_by=int(user_id),
            destination_id=int(destination_id),
            status="enviado",
            attempt=attempt,
            error_code=None,
            requested_at=requested_at,
            completed_at=self._now().replace(microsecond=0),
            idempotency_key=key,
        )
        LOGGER.info(
            "Report delivered report_id=%s user_id=%s destination_id=%s attempt=%s",
            report_id, user_id, destination_id, attempt,
        )
        return self._view(delivery)


__all__ = ["ReportMessagingService"]
