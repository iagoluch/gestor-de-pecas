"""Contratos de explicabilidade e exceções para a visão gerencial.

Os contratos permanecem independentes do adaptador HTTP e da apresentação.
Eles carregam valores já calculados pelos serviços canônicos, referências,
desvios e a evidência que sustenta cada leitura.
"""

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Optional

from mes.contracts.management import MetricValue, json_value


@dataclass(frozen=True)
class InsightEvidence:
    source: str
    kind: str
    source_id: Optional[str] = None
    sector: Optional[str] = None
    resource: Optional[str] = None
    op: Optional[str] = None
    operation: Optional[str] = None
    product: Optional[str] = None
    reason: Optional[str] = None
    occurred_at: Optional[datetime] = None
    start: Optional[datetime] = None
    end: Optional[datetime] = None
    duration_seconds: Optional[float] = None
    quantity: Optional[int] = None
    details: dict = field(default_factory=dict)

    def to_dict(self):
        return json_value(asdict(self))


@dataclass(frozen=True)
class ManagementException:
    id: str
    type: str
    severity: str
    priority: int
    entity_type: str
    entity_id: str
    title: str
    summary: str
    justification: str
    period: dict
    sector: Optional[str] = None
    resource: Optional[str] = None
    op: Optional[str] = None
    operation: Optional[str] = None
    current_value: Optional[float] = None
    reference_value: Optional[float] = None
    deviation: Optional[float] = None
    unit: Optional[str] = None
    cause: Optional[str] = None
    impact_value: Optional[float] = None
    impact_unit: Optional[str] = None
    evidence: tuple[InsightEvidence, ...] = field(default_factory=tuple)

    def to_dict(self):
        data = asdict(self)
        data["period"] = json_value(self.period)
        data["evidence"] = [item.to_dict() for item in self.evidence]
        return data


@dataclass(frozen=True)
class KpiExplanation:
    key: str
    label: str
    metric: MetricValue
    period: dict
    components: tuple[dict, ...] = field(default_factory=tuple)
    largest_impact: Optional[dict] = None
    causes: tuple[dict, ...] = field(default_factory=tuple)
    resources: tuple[dict, ...] = field(default_factory=tuple)
    evidence: tuple[InsightEvidence, ...] = field(default_factory=tuple)
    calculation_policy: str = "backend_only"
    simulation_only: bool = False
    limitation: Optional[str] = None

    def to_dict(self):
        return {
            "key": self.key,
            "label": self.label,
            "metric": self.metric.to_dict(),
            "period": json_value(self.period),
            "components": json_value(self.components),
            "largest_impact": json_value(self.largest_impact),
            "causes": json_value(self.causes),
            "resources": json_value(self.resources),
            "evidence": [item.to_dict() for item in self.evidence],
            "calculation_policy": self.calculation_policy,
            "simulation_only": self.simulation_only,
            "limitation": self.limitation,
        }
