"""Custo de paradas e de horas trabalhadas para a aba Diretoria (16/10/2026).

Fórmula por trecho: horas x (R$/h do recurso + soma dos R$/h das pessoas
alocadas no trecho). Quem não tem custo cadastrado conta como R$ 0, o
resultado fica ``completo=False`` e o nome do faltante é listado.

Este módulo é puro: sem banco, sem relógio, sem I/O.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Mapping, Sequence

_MICROS_PER_HOUR = Decimal(3_600_000_000)
_CENTAVO = Decimal("0.01")
_ZERO = Decimal("0")


@dataclass(frozen=True)
class StopSlice:
    """Trecho de tempo de um recurso, com as pessoas alocadas nele."""

    recurso: str
    inicio: datetime
    fim: datetime
    pessoas: tuple[str, ...]


@dataclass(frozen=True)
class CostRates:
    """Valores por hora. Chaves em maiúsculas (recurso e crachá)."""

    recurso: Mapping[str, Decimal]
    pessoa: Mapping[str, Decimal]


@dataclass(frozen=True)
class CostResult:
    horas: float
    custo: Decimal
    completo: bool
    recursos_sem_custo: tuple[str, ...]
    pessoas_sem_custo: tuple[str, ...]


def stop_cost(stops: Sequence[StopSlice], rates: CostRates) -> CostResult:
    """Custo das paradas (tempo parado do recurso e da equipe alocada)."""
    return _cost(stops, rates)


def work_cost(stops: Sequence[StopSlice], rates: CostRates) -> CostResult:
    """Custo das horas trabalhadas. Mesma fórmula de ``stop_cost``."""
    return _cost(stops, rates)


def _key(value: str) -> str:
    return str(value or "").strip().upper()


def _micros(stop: StopSlice) -> int:
    # Duração negativa ou zero não gera hora (decisão 16/10/2026).
    return max(0, (stop.fim - stop.inicio) // timedelta(microseconds=1))


def _cost(stops: Sequence[StopSlice], rates: CostRates) -> CostResult:
    total_micros = 0
    total_custo = _ZERO
    recursos_faltantes: set[str] = set()
    pessoas_faltantes: set[str] = set()

    for stop in stops:
        micros = _micros(stop)
        total_micros += micros
        horas = Decimal(micros) / _MICROS_PER_HOUR

        recurso = _key(stop.recurso)
        taxa_recurso = rates.recurso.get(recurso)
        if taxa_recurso is None:
            recursos_faltantes.add(recurso)
            taxa_recurso = _ZERO

        taxa_pessoas = _ZERO
        for cracha in {_key(p) for p in stop.pessoas} - {""}:
            taxa_pessoa = rates.pessoa.get(cracha)
            if taxa_pessoa is None:
                pessoas_faltantes.add(cracha)
                taxa_pessoa = _ZERO
            taxa_pessoas += taxa_pessoa

        total_custo += horas * (taxa_recurso + taxa_pessoas)

    return CostResult(
        horas=total_micros / 3_600_000_000,
        custo=total_custo.quantize(_CENTAVO, rounding=ROUND_HALF_UP),
        completo=not recursos_faltantes and not pessoas_faltantes,
        recursos_sem_custo=tuple(sorted(recursos_faltantes)),
        pessoas_sem_custo=tuple(sorted(pessoas_faltantes)),
    )
