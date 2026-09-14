"""Contratos neutros para relatórios industriais e seus artefatos."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta
import hashlib
import json
from typing import Any

from mes.contracts.management import AnalyticsFilter


REPORT_TYPES = (
    "completo",
    "gerencial",
    "producao",
    "ops",
    "paradas",
    "setup",
    "qualidade",
    "indicadores",
    "recursos",
    "setores",
    "nestings",
    "excecoes",
    "rastreabilidade",
    "auditoria",
)
REPORT_PERIOD_KINDS = (
    "hoje",
    "ontem",
    "esta_semana",
    "semana_anterior",
    "este_mes",
    "mes_anterior",
    "personalizado",
)
MAX_REPORT_PERIOD = timedelta(days=366)


class ReportError(RuntimeError):
    def __init__(self, code: str, user_message: str, *, status_code: int = 400):
        super().__init__(user_message)
        self.code = code
        self.user_message = user_message
        self.status_code = status_code


@dataclass(frozen=True)
class ReportRequest:
    report_type: str
    inicio: datetime
    fim: datetime
    setor: str | None = None
    recurso: str | None = None
    op: str | None = None
    indicador: str | None = None
    include_executive_analysis: bool = False

    def __post_init__(self):
        normalized = str(self.report_type or "").strip().casefold().replace("-", "_")
        if normalized not in REPORT_TYPES:
            raise ReportError("report_type_not_allowed", "O tipo de relatório não é permitido.")
        object.__setattr__(self, "report_type", normalized)
        if self.fim <= self.inicio:
            raise ReportError("invalid_report_period", "O fim do período deve ser posterior ao início.")
        if self.fim - self.inicio > MAX_REPORT_PERIOD:
            raise ReportError("report_period_too_large", "O período máximo do relatório é de 366 dias.")
        if normalized == "rastreabilidade" and not str(self.op or "").strip():
            raise ReportError("report_op_required", "Informe a OP para o relatório de rastreabilidade.")

    def analytics_filter(self) -> AnalyticsFilter:
        return AnalyticsFilter(
            inicio=self.inicio,
            fim=self.fim,
            setor=self.setor,
            recurso=self.recurso,
            op=self.op,
        )

    def filters_dict(self) -> dict[str, Any]:
        return {
            key: value
            for key, value in {
                "setor": self.setor,
                "recurso": self.recurso,
                "op": self.op,
                "indicador": self.indicador,
                "include_executive_analysis": self.include_executive_analysis,
            }.items()
            if value not in (None, "", False)
        }


def build_report_idempotency_key(
    request: "ReportRequest",
    *,
    created_by: int,
    source: str,
) -> str:
    """Chave determinística de uma solicitação de relatório.

    Duas solicitações semanticamente iguais produzem a mesma chave, e a
    constraint ``uq_generated_reports_idempotency`` transforma isso em um único
    artifact. A chave nunca usa nome de arquivo nem UUID aleatório: só entram
    dados normalizados da própria solicitação.

    ``source`` participa da chave porque um relatório pedido pelo chat e outro
    pedido manualmente são solicitações distintas do ponto de vista de auditoria,
    ainda que produzam o mesmo conteúdo.
    """

    def texto(value: Any) -> str | None:
        # Ausência e string vazia colapsam no mesmo valor.
        cleaned = str(value or "").strip()
        return cleaned.casefold() or None

    payload = {
        "created_by": int(created_by),
        "source": texto(source),
        "report_type": texto(request.report_type),
        # Segundos bastam: o contrato já descarta microssegundos.
        "inicio": request.inicio.replace(microsecond=0).isoformat(),
        "fim": request.fim.replace(microsecond=0).isoformat(),
        "setor": texto(request.setor),
        "recurso": texto(request.recurso),
        "op": texto(request.op),
        "indicador": texto(request.indicador),
        "include_executive_analysis": bool(request.include_executive_analysis),
    }
    # sort_keys fixa a ordem dos campos; separadores sem espaço evitam variação.
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "report:v1:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def resolve_report_period(
    period_kind: str,
    *,
    now: datetime,
    inicio: datetime | None = None,
    fim: datetime | None = None,
) -> tuple[datetime, datetime]:
    """Resolve atalhos temporais no backend, sem depender do relógio do LLM."""

    kind = str(period_kind or "").strip().casefold()
    if kind not in REPORT_PERIOD_KINDS:
        raise ReportError("report_period_kind_not_allowed", "O período solicitado não é permitido.")
    current = now.replace(microsecond=0)
    today = datetime.combine(current.date(), time.min)
    if kind == "hoje":
        return today, current
    if kind == "ontem":
        return today - timedelta(days=1), today
    week_start = today - timedelta(days=today.weekday())
    if kind == "esta_semana":
        return week_start, current
    if kind == "semana_anterior":
        return week_start - timedelta(days=7), week_start
    month_start = today.replace(day=1)
    if kind == "este_mes":
        return month_start, current
    if kind == "mes_anterior":
        previous_end = month_start
        previous_start = (previous_end - timedelta(days=1)).replace(day=1)
        return previous_start, previous_end
    if inicio is None or fim is None:
        raise ReportError(
            "custom_report_period_required",
            "O período personalizado exige data inicial e final.",
        )
    return inicio.replace(microsecond=0), fim.replace(microsecond=0)


__all__ = [
    "MAX_REPORT_PERIOD",
    "build_report_idempotency_key",
    "REPORT_PERIOD_KINDS",
    "REPORT_TYPES",
    "ReportError",
    "ReportRequest",
    "resolve_report_period",
]
