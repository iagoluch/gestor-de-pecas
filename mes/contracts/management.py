"""DTOs estáveis para consumidores de analytics.

Usamos dataclasses da biblioteca padrão para não amarrar o domínio a FastAPI,
frameworks de transporte. A API pode serializar ``to_dict()`` diretamente.
"""

from dataclasses import asdict, dataclass
from datetime import date, datetime
from typing import Any, Optional

from mes.domain import DataAvailability


def json_value(value: Any):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_value(item) for item in value]
    return value


@dataclass(frozen=True)
class AnalyticsFilter:
    inicio: datetime
    fim: datetime
    setor: Optional[str] = None
    recurso: Optional[str] = None
    turno: Optional[str] = None
    op: Optional[str] = None
    operacao: Optional[str] = None
    produto: Optional[str] = None
    operador: Optional[str] = None

    def to_dict(self):
        return json_value(asdict(self))


@dataclass(frozen=True)
class MetricValue:
    value: Optional[float]
    availability: DataAvailability = DataAvailability.AVAILABLE
    unit: Optional[str] = None
    reason: Optional[str] = None

    def to_dict(self):
        data = asdict(self)
        data["availability"] = self.availability.value
        return json_value(data)


@dataclass(frozen=True)
class NestingTiming:
    apontamento_id: Optional[int]
    plano_hash: str
    tarefa: str
    programa: str
    nesting: int
    maquina: str
    material: Optional[str]
    espessura: Optional[float]
    inicio: Optional[datetime]
    fim: Optional[datetime]
    previsto_segundos: Optional[float]
    real_segundos: Optional[float]
    desvio_segundos: Optional[float]
    desvio_percentual: Optional[float]
    status: str
    real_periodo_segundos: Optional[float] = None
    operador_inicio: Optional[str] = None
    operador_fim: Optional[str] = None

    def to_dict(self):
        return json_value(asdict(self))
