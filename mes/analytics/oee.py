"""Cálculo canônico de OEE e de seus componentes.

Esta função preserva a regra validada que antes estava embutida no
``ManagementService`` e condicionada ao modo de simulação. Consumidores
recebem os indicadores prontos; nenhum deles deve recompor a fórmula.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from mes.contracts import MetricValue
from mes.domain import DataAvailability, EventCategory


PERCENT_SCALE = 100.0
OEE_CONTRACT = {
    "source": "mes.analytics.oee.calculate_oee",
    "unit": "percent_0_100",
    "backend_rounding": "full_precision",
    "presentation_rounding": "one_decimal",
}


@dataclass(frozen=True)
class OeeCalculation:
    availability: MetricValue
    performance: MetricValue
    ftt: MetricValue
    oee: MetricValue
    time_bases: dict[str, float]

    def metrics_dict(self) -> dict[str, dict]:
        return {
            "availability": self.availability.to_dict(),
            "performance": self.performance.to_dict(),
            "ftt": self.ftt.to_dict(),
            "oee": self.oee.to_dict(),
        }


def oee_seconds_by_category(
    seconds_by_category: Mapping[EventCategory, float],
    *,
    planned_downtime_seconds: float = 0.0,
) -> dict[EventCategory, float]:
    """Base temporal do OEE a partir do tempo físico medido.

    A fórmula do OEE não muda: o que muda é a entrada. Parada planejada (almoço,
    café, reunião, limpeza, fora de turno sem hora extra e demais motivos do
    grupo ``PARADA PROGRAMADA``) sai do tempo disponível, exatamente como o
    intervalo cadastrado do turno já sai da disponibilidade do calendário.
    Parada não planejada permanece e continua penalizando a Disponibilidade.

    ``fora_turno`` e ``fila`` não participam do cálculo. ``sem_demanda`` é
    tempo em que o recurso estava disponível, mas sem programação: permanece
    na base para resultar em 100% de Disponibilidade e 0% de Performance
    quando ocupar sozinho o período.
    """

    base = {
        category: max(0.0, float(value or 0.0))
        for category, value in dict(seconds_by_category).items()
    }
    planned = max(0.0, float(planned_downtime_seconds or 0.0))
    if planned:
        measured_downtime = max(0.0, float(base.get(EventCategory.DOWNTIME, 0.0) or 0.0))
        base[EventCategory.DOWNTIME] = max(0.0, measured_downtime - planned)
    return base


def calculate_oee(
    *,
    seconds_by_category: Mapping[EventCategory, float],
    good_quantity: int,
    scrap_quantity: int,
    rework_quantity: int,
    standard_run_seconds: float,
) -> OeeCalculation:
    """Aplica exatamente a regra oficial vigente do Gestor de Peças.

    Setup, retrabalho e atividade sem OP permanecem tempo produtivo de apoio.
    Quantidade boa, refugo e retrabalho continuam grandezas separadas.

    Recurso sem demanda compõe o tempo disponível e a base de Performance:
    ele estava apto a trabalhar (Disponibilidade 100%), mas não produziu
    (Performance 0%). Fila vinculada a OP e fora de turno continuam fora.
    """

    def seconds(category: EventCategory) -> float:
        return max(0.0, float(seconds_by_category.get(category, 0.0) or 0.0))

    available_seconds = sum(
        seconds(category)
        for category in (
            EventCategory.PRODUCTION,
            EventCategory.SETUP,
            EventCategory.REWORK,
            EventCategory.ACTIVITY_WITHOUT_OP,
            EventCategory.NO_DEMAND,
            EventCategory.DOWNTIME,
            EventCategory.UNKNOWN,
        )
    )
    no_demand_seconds = seconds(EventCategory.NO_DEMAND)
    queue_seconds = seconds(EventCategory.QUEUE)
    worked_seconds = sum(
        seconds(category)
        for category in (
            EventCategory.PRODUCTION,
            EventCategory.SETUP,
            EventCategory.REWORK,
            EventCategory.ACTIVITY_WITHOUT_OP,
            EventCategory.NO_DEMAND,
        )
    )
    # Fila já saiu da base disponível. Ausência de demanda permanece porque o
    # recurso estava disponível, mas sem produção; por isso também compõe a
    # base da Performance.
    operational_seconds = available_seconds
    productive_gross_seconds = seconds(EventCategory.PRODUCTION)
    supporting_productive_seconds = sum(
        seconds(category)
        for category in (
            EventCategory.SETUP,
            EventCategory.REWORK,
            EventCategory.ACTIVITY_WITHOUT_OP,
        )
    )
    quality_total = (
        max(0, int(good_quantity))
        + max(0, int(scrap_quantity))
        + max(0, int(rework_quantity))
    )
    productive_net_seconds = max(0.0, float(standard_run_seconds or 0.0)) + supporting_productive_seconds

    availability_ratio = worked_seconds / available_seconds if available_seconds > 0 else None
    performance_ratio = productive_net_seconds / worked_seconds if worked_seconds > 0 else None
    ftt_ratio = max(0, int(good_quantity)) / quality_total if quality_total > 0 else None
    if availability_ratio is not None and performance_ratio == 0:
        # Sem produção, a Performance zera o produto do OEE mesmo quando o
        # FTT não é aplicável por inexistir quantidade inspecionada.
        oee_ratio = 0.0
    elif (
        availability_ratio is not None
        and performance_ratio is not None
        and ftt_ratio is not None
    ):
        oee_ratio = availability_ratio * performance_ratio * ftt_ratio
    else:
        oee_ratio = None

    availability = _percent_metric(
        availability_ratio,
        "Não há tempo físico medido no filtro para calcular a Disponibilidade.",
    )
    performance = _percent_metric(
        performance_ratio,
        "Não há tempo trabalhado no filtro para calcular a Performance.",
    )
    ftt = _percent_metric(
        ftt_ratio,
        "Não há quantidade boa, refugo ou retrabalho no filtro para calcular o FTT.",
    )
    missing_components = [
        name
        for name, ratio in (
            ("Disponibilidade", availability_ratio),
            ("Performance", performance_ratio),
            ("FTT", ftt_ratio),
        )
        if ratio is None
    ]
    oee = MetricValue(
        value=oee_ratio * PERCENT_SCALE if oee_ratio is not None else None,
        availability=(
            DataAvailability.AVAILABLE
            if oee_ratio is not None
            else (
                DataAvailability.NO_RECORDS
                if len(missing_components) == 3
                else DataAvailability.INSUFFICIENT_DATA
            )
        ),
        unit="%",
        reason=(
            None
            if oee_ratio is not None
            else "OEE indisponível no filtro por falta de dados para: "
            + ", ".join(missing_components)
            + "."
        ),
    )

    return OeeCalculation(
        availability=availability,
        performance=performance,
        ftt=ftt,
        oee=oee,
        time_bases={
            "available_seconds": available_seconds,
            "operational_seconds": operational_seconds,
            "worked_seconds": worked_seconds,
            "productive_gross_seconds": productive_gross_seconds,
            "productive_net_seconds": productive_net_seconds,
            "performance_difference_seconds": productive_net_seconds - worked_seconds,
            "standard_run_seconds": max(0.0, float(standard_run_seconds or 0.0)),
            "supporting_productive_seconds": supporting_productive_seconds,
            # Fora da fórmula, dentro do relatório: o tempo sem demanda é o
            # bucket que o gestor precisa ver separado de fora de turno.
            "no_demand_seconds": no_demand_seconds,
            "queue_seconds": queue_seconds,
        },
    )


def _percent_metric(ratio: float | None, missing_reason: str) -> MetricValue:
    return MetricValue(
        value=ratio * PERCENT_SCALE if ratio is not None else None,
        availability=(
            DataAvailability.AVAILABLE if ratio is not None else DataAvailability.NO_RECORDS
        ),
        unit="%",
        reason=None if ratio is not None else missing_reason,
    )
