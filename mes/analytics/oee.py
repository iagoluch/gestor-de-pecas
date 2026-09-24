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
OEE_METHODOLOGY = "CORPORATIVA"
# Muda sempre que uma regra do cálculo mudar, para que o resultado publicado
# identifique a regra que o produziu.
OEE_RULE_VERSION = "corporativa-2026-09-24"
RESULT_ORIGIN_FORMULA = "FORMULA_CORPORATIVA"
RESULT_ORIGIN_NO_DEMAND = "REGRA_CORPORATIVA_SEM_DEMANDA"
PERFORMANCE_ABOVE_LIMIT_ALERT = "PERFORMANCE_ACIMA_DE_100"
OEE_CONTRACT = {
    "source": "mes.analytics.oee.calculate_oee",
    "unit": "percent_0_100",
    "backend_rounding": "full_precision",
    "presentation_rounding": "one_decimal",
    "methodology": OEE_METHODOLOGY,
    "rule_version": OEE_RULE_VERSION,
}

_WORKED_CATEGORIES = (
    EventCategory.PRODUCTION,
    EventCategory.SETUP,
    EventCategory.REWORK,
    EventCategory.ACTIVITY_WITHOUT_OP,
)
_SUPPORTING_CATEGORIES = (
    EventCategory.SETUP,
    EventCategory.REWORK,
    EventCategory.ACTIVITY_WITHOUT_OP,
)


@dataclass(frozen=True)
class OeeCalculation:
    availability: MetricValue
    performance: MetricValue
    ftt: MetricValue
    oee: MetricValue
    time_bases: dict[str, float]
    result_origin: str = RESULT_ORIGIN_FORMULA
    alerts: tuple[str, ...] = ()

    @property
    def is_no_demand_exception(self) -> bool:
        return self.result_origin == RESULT_ORIGIN_NO_DEMAND

    def metrics_dict(self) -> dict[str, dict]:
        return {
            "availability": self.availability.to_dict(),
            "performance": self.performance.to_dict(),
            "ftt": self.ftt.to_dict(),
            "oee": self.oee.to_dict(),
        }

    def trace_dict(self) -> dict:
        """Rastreabilidade do resultado: metodologia, versão, origem e alertas."""

        return {
            "methodology": OEE_METHODOLOGY,
            "rule_version": OEE_RULE_VERSION,
            "result_origin": self.result_origin,
            "alerts": list(self.alerts),
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
    good_without_standard_quantity: int = 0,
) -> OeeCalculation:
    """Aplica a metodologia corporativa vigente do Gestor de Peças.

    Disponibilidade = T_trabalhado / T_disponivel
    Performance     = (S_boas + T_apoio) / T_trabalhado
    FTT             = boas / (boas + refugo + retrabalho)

    Setup, retrabalho e atividade sem OP são tempo trabalhado e crédito de
    apoio. Recurso sem demanda não entra em nenhuma das bases: em período
    misto ele aparece no relatório sem reduzir Disponibilidade nem
    Performance. Quando ocupa sozinho todo o tempo elegível, vale a exceção
    corporativa explícita: 100% / 0% / 0%, FTT indisponível.

    ``good_without_standard_quantity`` conta as peças boas sem tempo padrão
    cadastrado. Sem padrão, ``S_boas`` subestima o trabalho realizado; a
    Performance é bloqueada (nenhuma cobertura) ou marcada parcial.
    """

    def seconds(category: EventCategory) -> float:
        return max(0.0, float(seconds_by_category.get(category, 0.0) or 0.0))

    worked_seconds = sum(seconds(category) for category in _WORKED_CATEGORIES)
    available_seconds = (
        worked_seconds
        + seconds(EventCategory.DOWNTIME)
        + seconds(EventCategory.UNKNOWN)
    )
    no_demand_seconds = seconds(EventCategory.NO_DEMAND)
    queue_seconds = seconds(EventCategory.QUEUE)
    productive_gross_seconds = seconds(EventCategory.PRODUCTION)
    supporting_productive_seconds = sum(
        seconds(category) for category in _SUPPORTING_CATEGORIES
    )
    good = max(0, int(good_quantity))
    quality_total = good + max(0, int(scrap_quantity)) + max(0, int(rework_quantity))
    standard_run = max(0.0, float(standard_run_seconds or 0.0))
    productive_net_seconds = standard_run + supporting_productive_seconds

    time_bases = {
        "available_seconds": available_seconds,
        "operational_seconds": available_seconds,
        "worked_seconds": worked_seconds,
        "productive_gross_seconds": productive_gross_seconds,
        "productive_net_seconds": productive_net_seconds,
        "performance_difference_seconds": productive_net_seconds - worked_seconds,
        "standard_run_seconds": standard_run,
        "supporting_productive_seconds": supporting_productive_seconds,
        # Fora da fórmula no período misto, dentro do relatório: o gestor vê
        # o tempo sem demanda separado de fila e de fora de turno.
        "no_demand_seconds": no_demand_seconds,
        "queue_seconds": queue_seconds,
    }

    if _is_fully_no_demand(
        available_seconds=available_seconds,
        no_demand_seconds=no_demand_seconds,
        queue_seconds=queue_seconds,
        quality_total=quality_total,
    ):
        return _no_demand_exception(time_bases, no_demand_seconds)

    availability_ratio = worked_seconds / available_seconds if available_seconds > 0 else None
    availability = _percent_metric(
        availability_ratio,
        "Não há tempo físico medido no filtro para calcular a Disponibilidade.",
    )
    performance, performance_alerts = _performance_metric(
        productive_net_seconds=productive_net_seconds,
        worked_seconds=worked_seconds,
        good_quantity=good,
        good_without_standard_quantity=good_without_standard_quantity,
    )
    ftt_ratio = good / quality_total if quality_total > 0 else None
    ftt = _percent_metric(
        ftt_ratio,
        "Não há quantidade boa, refugo ou retrabalho no filtro para calcular o FTT.",
    )
    oee = _oee_metric(availability, performance, ftt)
    return OeeCalculation(
        availability=availability,
        performance=performance,
        ftt=ftt,
        oee=oee,
        time_bases=time_bases,
        alerts=performance_alerts,
    )


def _is_fully_no_demand(
    *,
    available_seconds: float,
    no_demand_seconds: float,
    queue_seconds: float,
    quality_total: int,
) -> bool:
    """Todo o tempo elegível do período é sem demanda.

    Fora de turno e pausas excluídas já saíram da base. Qualquer produção,
    apoio, parada, estado desconhecido (lacuna de dados), fila de OP ou
    quantidade registrada é incompatível com a exceção.
    """

    return (
        no_demand_seconds > 0
        and available_seconds == 0
        and queue_seconds == 0
        and quality_total == 0
    )


def _no_demand_exception(time_bases: dict[str, float], no_demand_seconds: float) -> OeeCalculation:
    # O zero do OEE é decisão de negócio, não produto de 1 × 0 × null.
    reason = (
        "Exceção corporativa: período integralmente sem demanda "
        "(Disponibilidade 100%, Performance 0%, OEE 0%)."
    )
    return OeeCalculation(
        availability=MetricValue(100.0, DataAvailability.AVAILABLE, "%", reason),
        performance=MetricValue(0.0, DataAvailability.AVAILABLE, "%", reason),
        ftt=MetricValue(
            None,
            DataAvailability.NOT_APPLICABLE,
            "%",
            "Sem quantidade produzida no período integralmente sem demanda.",
        ),
        oee=MetricValue(0.0, DataAvailability.AVAILABLE, "%", reason),
        time_bases={
            **time_bases,
            "available_seconds": no_demand_seconds,
            "operational_seconds": no_demand_seconds,
        },
        result_origin=RESULT_ORIGIN_NO_DEMAND,
    )


def _performance_metric(
    *,
    productive_net_seconds: float,
    worked_seconds: float,
    good_quantity: int,
    good_without_standard_quantity: int,
) -> tuple[MetricValue, tuple[str, ...]]:
    if worked_seconds <= 0:
        return _percent_metric(
            None, "Não há tempo trabalhado no filtro para calcular a Performance."
        ), ()
    missing = min(good_quantity, max(0, int(good_without_standard_quantity or 0)))
    if good_quantity > 0 and missing == good_quantity:
        return MetricValue(
            None,
            DataAvailability.NOT_CONFIGURED,
            "%",
            f"Tempo padrão ausente para as {good_quantity} peças boas; "
            "Performance bloqueada até o cadastro do tempo padrão.",
        ), ()
    ratio = productive_net_seconds / worked_seconds
    value = ratio * PERCENT_SCALE
    if ratio > 1:
        # Sem corte silencioso: o valor bruto fica visível com o alerta.
        return MetricValue(
            value,
            DataAvailability.AVAILABLE,
            "%",
            "Performance acima de 100%: investigar tempo padrão, unidade, "
            "simultaneidade ou duplicação de apontamentos.",
        ), (PERFORMANCE_ABOVE_LIMIT_ALERT,)
    if missing:
        return MetricValue(
            value,
            DataAvailability.PARTIAL,
            "%",
            f"Tempo padrão ausente para {missing} de {good_quantity} peças boas; "
            "Performance subestimada e não homologável.",
        ), ()
    return MetricValue(value, DataAvailability.AVAILABLE, "%", None), ()


def _oee_metric(availability: MetricValue, performance: MetricValue, ftt: MetricValue) -> MetricValue:
    components = (
        ("Disponibilidade", availability),
        ("Performance", performance),
        ("FTT", ftt),
    )
    missing = [name for name, metric in components if metric.value is None]
    if missing:
        return MetricValue(
            None,
            (
                DataAvailability.NO_RECORDS
                if len(missing) == 3
                else DataAvailability.INSUFFICIENT_DATA
            ),
            "%",
            "OEE indisponível no filtro por falta de dados para: " + ", ".join(missing) + ".",
        )
    value = availability.value * performance.value * ftt.value / (PERCENT_SCALE ** 2)
    if performance.availability is DataAvailability.PARTIAL:
        return MetricValue(value, DataAvailability.PARTIAL, "%", performance.reason)
    return MetricValue(value, DataAvailability.AVAILABLE, "%", None)


def _percent_metric(ratio: float | None, missing_reason: str) -> MetricValue:
    return MetricValue(
        value=ratio * PERCENT_SCALE if ratio is not None else None,
        availability=(
            DataAvailability.AVAILABLE if ratio is not None else DataAvailability.NO_RECORDS
        ),
        unit="%",
        reason=None if ratio is not None else missing_reason,
    )
