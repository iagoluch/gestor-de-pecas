"""Adapters canônicos das fontes heterogêneas do Gestor de Peças.

Nenhum adapter escreve no banco. Eles transformam registros existentes em um
vocabulário único para analytics, rastreabilidade, exportações e futura API Web.
"""

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Optional

from mes.domain import EventCategory


@dataclass(frozen=True)
class CanonicalFact:
    source: str
    source_id: str
    entity: str
    sector: Optional[str]
    resource: Optional[str]
    op: Optional[str]
    operation: Optional[str]
    product: Optional[str]
    start: Optional[datetime]
    end: Optional[datetime]
    category: EventCategory
    good_quantity: int = 0
    scrap_quantity: int = 0
    rework_quantity: int = 0
    metadata: Optional[dict] = None

    def to_dict(self):
        data = asdict(self)
        data["category"] = self.category.value
        for key in ("start", "end"):
            if data[key] is not None:
                data[key] = data[key].isoformat()
        return data


def operator_appointment_fact(row) -> CanonicalFact:
    status = str(row.get("status") or "").casefold()
    category = {
        "em processo": EventCategory.PRODUCTION,
        "parada": EventCategory.DOWNTIME,
        "setup": EventCategory.SETUP,
        "retrabalho": EventCategory.REWORK,
    }.get(status, EventCategory.UNKNOWN)
    return CanonicalFact(
        source="apontamentos_operacionais",
        source_id=str(row.get("id") or ""),
        entity="operation",
        sector=row.get("tipo_setor"),
        resource=row.get("maquina"),
        op=row.get("op"),
        operation=row.get("numero_operacao"),
        product=row.get("produto_codigo") or row.get("peca"),
        start=_dt(row.get("data_inicio")),
        end=_dt(row.get("data_fim")),
        category=category,
        good_quantity=int(row.get("quantidade_boa") or 0),
        scrap_quantity=int(row.get("quantidade_refugo") or 0),
        rework_quantity=int(row.get("quantidade_retrabalho") or 0),
        metadata={
            "route_resource": row.get("codigo_recurso"),
            "actual_resource": row.get("maquina"),
            "lot": row.get("lote"),
        },
    )


def cut_nesting_fact(row) -> CanonicalFact:
    return CanonicalFact(
        source="apontamentos_corte",
        source_id=str(row.get("apontamento_id") or row.get("id") or ""),
        entity="nesting",
        sector="Corte",
        resource=row.get("maquina"),
        op=None,
        operation=None,
        product=None,
        start=_dt(row.get("inicio") or row.get("data_inicio")),
        end=_dt(row.get("fim") or row.get("data_fim")),
        category=EventCategory.PRODUCTION,
        metadata={
            "task": row.get("tarefa") or row.get("codigo_tarefa"),
            "program": row.get("programa"),
            "nesting": row.get("nesting") or row.get("sequencia_nesting"),
            "plan_hash": row.get("plano_hash"),
            "planned_seconds": row.get("previsto_segundos") or row.get("tempo_previsto_segundos"),
            "real_seconds": row.get("real_segundos") or row.get("tempo_real_segundos"),
            "material": row.get("material"),
            "thickness": row.get("espessura"),
        },
    )


def _dt(value):
    if value is None or isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
