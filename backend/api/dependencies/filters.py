"""Filtros gerenciais tipados e limitados no servidor."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta
import math

from fastapi import Query, Request

from backend.api.errors import AppError
from mes.contracts import AnalyticsFilter

# Fora desse intervalo a data não representa um período de negócio real
# (o sistema não tem histórico antes disso nem opera no futuro distante).
# Sem esse limite, uma data extrema como ano 0263 passava pelas checagens de
# "fim > início" e "período <= 366 dias" e só quebrava na consulta ao banco,
# virando 500 em vez de ser rejeitada como entrada inválida.
_MIN_VALID_YEAR = 2000
_MAX_YEARS_IN_FUTURE = 1


def _reject_implausible_date(value: datetime, current: datetime) -> None:
    if value.year < _MIN_VALID_YEAR or value.year > current.year + _MAX_YEARS_IN_FUTURE:
        raise AppError(
            "invalid_date",
            "A data informada está fora do intervalo permitido.",
            status_code=422,
        )


def _to_local_naive(value: datetime) -> datetime:
    # O relógio e o banco trabalham em horário local ingênuo. Uma data com
    # fuso (ex.: sufixo "Z") comparada a eles lançava TypeError e virava 500.
    if value.tzinfo is None:
        return value
    try:
        return value.astimezone().replace(tzinfo=None)
    except (OverflowError, ValueError, OSError):
        raise AppError(
            "invalid_date",
            "A data informada está fora do intervalo permitido.",
            status_code=422,
        ) from None


def validated_business_datetime(value: datetime | None, current: datetime) -> datetime | None:
    """Contrato único para datas de período vindas da API: rejeita ano
    implausível (422 invalid_date) e devolve horário local ingênuo."""
    if value is None:
        return None
    _reject_implausible_date(value, current)
    return _to_local_naive(value)


def request_now(request: Request) -> datetime:
    clock = getattr(request.app.state, "clock", None)
    return clock.now() if clock is not None else datetime.now().replace(microsecond=0)


def analytics_filter(
    request: Request,
    inicio: datetime | None = Query(default=None),
    fim: datetime | None = Query(default=None),
    setor: str | None = Query(default=None, max_length=120),
    recurso: str | None = Query(default=None, max_length=120),
    turno: str | None = Query(default=None, max_length=80),
    op: str | None = Query(default=None, max_length=120),
    operacao: str | None = Query(default=None, max_length=120),
    produto: str | None = Query(default=None, max_length=160),
    operador: str | None = Query(default=None, max_length=160),
) -> AnalyticsFilter:
    current = request_now(request)
    fim = validated_business_datetime(fim, current)
    inicio = validated_business_datetime(inicio, current)
    end = fim or current
    settings = getattr(request.app.state, "settings", None)
    simulation_now = current if getattr(settings, "simulation_mode", False) else None
    if getattr(settings, "simulation_mode", False) and simulation_now is not None:
        end = min(end, simulation_now)
    start = inicio or datetime.combine(end.date(), time.min)
    if end <= start:
        raise AppError("invalid_period", "O fim do período deve ser posterior ao início.")
    if end - start > timedelta(days=366):
        raise AppError(
            "period_too_large",
            "O período máximo por consulta é de 366 dias.",
        )
    values = {
        "setor": setor,
        "recurso": recurso,
        "turno": turno,
        "op": op,
        "operacao": operacao,
        "produto": produto,
        "operador": operador,
    }
    values = {
        key: (str(value).strip() or None) if value is not None else None
        for key, value in values.items()
    }
    return AnalyticsFilter(inicio=start, fim=end, **values)


@dataclass(frozen=True)
class PageParams:
    page: int
    page_size: int

    def slice(self, items):
        start = (self.page - 1) * self.page_size
        return list(items)[start:start + self.page_size]

    def meta(self, total: int):
        return {
            "page": self.page,
            "page_size": self.page_size,
            "total": total,
            "pages": max(1, math.ceil(total / self.page_size)),
        }


def pagination(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=200),
) -> PageParams:
    return PageParams(page=page, page_size=page_size)
