"""Agendamento idempotente de relatórios para períodos já encerrados."""

from __future__ import annotations

import asyncio
from datetime import datetime, time, timedelta, timezone
import logging
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from mes.contracts.reports import ReportRequest


LOGGER = logging.getLogger(__name__)


def closed_report_period(frequency: str, local_now: datetime) -> tuple[datetime, datetime]:
    """Retorna o último dia, semana ou mês completo no fuso do agendamento."""

    current = local_now.replace(microsecond=0)
    today = datetime.combine(current.date(), time.min, tzinfo=current.tzinfo)
    normalized = str(frequency).casefold()
    if normalized == "diario":
        return today - timedelta(days=1), today
    week_start = today - timedelta(days=today.weekday())
    if normalized == "semanal":
        return week_start - timedelta(days=7), week_start
    if normalized == "quinzenal":
        # Quinzena fechada do calendário (1-15 / 16-fim do mês anterior),
        # mesmo padrão de janela fixa das demais frequências — evita que a
        # chave de idempotência mude todo dia (bug: janela móvel de 14 dias
        # disparava o envio diariamente em vez de 2x/mês).
        if current.day <= 15:
            first_half_start = today.replace(day=1)
            second_half_start = first_half_start - timedelta(days=1)
            second_half_start = second_half_start.replace(day=16)
            return second_half_start, first_half_start
        second_half_start = today.replace(day=16)
        return today.replace(day=1), second_half_start
    if normalized == "mensal":
        month_end = today.replace(day=1)
        return (month_end - timedelta(days=1)).replace(day=1), month_end
    raise ValueError("Frequência de relatório não permitida.")


class ReportScheduler:
    def __init__(self, repository, report_service, *, messaging_service=None):
        self.repository = repository
        self.report_service = report_service
        self.messaging_service = messaging_service

    async def run_due(self, now: datetime | None = None) -> list[dict]:
        utc_now = now or datetime.now(timezone.utc)
        if utc_now.tzinfo is None:
            utc_now = utc_now.replace(tzinfo=timezone.utc)
        results: list[dict] = []
        agendamentos = await asyncio.to_thread(
            self.repository.listar_agendamentos_relatorio, enabled_only=True
        )
        for schedule in agendamentos:
            schedule_id = int(schedule["id"])
            try:
                try:
                    local_now = utc_now.astimezone(ZoneInfo(str(schedule["timezone"])))
                except ZoneInfoNotFoundError as exc:
                    raise ValueError("Fuso horário inválido no agendamento.") from exc
                configured_time = schedule["run_time"]
                if local_now.time().replace(tzinfo=None) < configured_time:
                    continue
                start, end = closed_report_period(schedule["frequency"], local_now)
                filters = dict(schedule.get("filters") or {})
                request = ReportRequest(
                    report_type=schedule["report_type"],
                    inicio=start.replace(tzinfo=None),
                    fim=end.replace(tzinfo=None),
                    setor=filters.get("setor"),
                    recurso=filters.get("recurso"),
                    op=filters.get("op"),
                    indicador=filters.get("indicador"),
                    include_executive_analysis=bool(filters.get("include_executive_analysis", False)),
                )
                period_key = f"{start.date().isoformat()}:{end.date().isoformat()}"
                idempotency_key = f"schedule:{schedule_id}:{period_key}"
                artifact = await asyncio.to_thread(
                    self.report_service.generate,
                    request,
                    created_by=int(schedule["created_by"]),
                    source="automatico",
                    idempotency_key=idempotency_key,
                )
                outcome = {"schedule_id": schedule_id, "status": "gerado", "artifact": artifact}
                destination_id = schedule.get("destination_id")
                if destination_id is not None and self.messaging_service is not None:
                    outcome["delivery"] = await self.messaging_service.send_report(
                        artifact["id"],
                        user_id=int(schedule["created_by"]),
                        destination_id=int(destination_id),
                        idempotency_key=f"{idempotency_key}:destination:{destination_id}",
                    )
                results.append(outcome)
            except Exception as exc:
                LOGGER.exception("Scheduled report failed schedule_id=%s", schedule_id)
                results.append({
                    "schedule_id": schedule_id,
                    "status": "falhou",
                    "error_code": getattr(exc, "code", "report_schedule_failed"),
                })
        return results


__all__ = ["ReportScheduler", "closed_report_period"]
