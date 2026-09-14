"""Filtros gerenciais tipados e limitados no servidor."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta
import math

from fastapi import Query, Request

from backend.api.errors import AppError
from mes.contracts import AnalyticsFilter


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
    clock = getattr(request.app.state, "clock", None)
    current = clock.now() if clock is not None else datetime.now().replace(microsecond=0)
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
