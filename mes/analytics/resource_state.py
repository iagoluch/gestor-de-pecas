"""Conversão de estados físicos persistidos em segmentos analíticos."""

from __future__ import annotations

from datetime import datetime

from mes.analytics.physical_time import PhysicalInputSegment, consolidate_physical_time
from mes.domain import EventCategory, ManufacturingRules


#: Estados físicos que carregam classificação PLANEJADA/NÃO_PLANEJADA.
CLASSIFIABLE_STOP_CATEGORIES = (EventCategory.DOWNTIME, EventCategory.OUT_OF_SHIFT)


def classify_state_row(row) -> "object | None":
    """Classificação central da parada representada por um estado físico.

    A decisão vem do catálogo PCFactory (grupo/``planejado``) já materializado na
    consulta, do motivo canônico e, por último, da marca de interrupção
    programada do evento. Estados produtivos não recebem classificação.
    """

    row = dict(row or {})
    try:
        category = EventCategory(str(row.get("categoria") or ""))
    except ValueError:
        return None
    if category not in CLASSIFIABLE_STOP_CATEGORIES:
        return None
    return ManufacturingRules.classify_stop(
        category=category,
        status_row={
            "nome": row.get("status_nome"),
            "grupo_codigo": row.get("status_grupo_codigo") or row.get("grupo_codigo"),
            # Taxonomia do catálogo. O `planejado` do próprio evento é a marca de
            # interrupção programada e entra com precedência menor.
            "planejado": row.get("status_planejado"),
        },
        reason=row.get("motivo"),
        planned=row.get("planejado"),
    )


def build_physical_state_inputs(rows, *, inicio: datetime, fim: datetime):
    inputs = []
    for raw in rows or ():
        row = dict(raw)
        start = _dt(row.get("inicio_periodo") or row.get("data_inicio"))
        end = _dt(row.get("fim_periodo") or row.get("data_fim")) or fim
        if start is None:
            continue
        start = max(start, inicio)
        end = min(end, fim)
        if end <= start:
            continue
        try:
            category = EventCategory(str(row.get("categoria") or ""))
        except ValueError:
            category = EventCategory.UNKNOWN
        inputs.append(PhysicalInputSegment(
            resource=str(row.get("recurso") or "Não informado").strip() or "Não informado",
            sector=str(row.get("tipo_setor") or "Não informado").strip() or "Não informado",
            category=category,
            start=start,
            end=end,
            source_ref=f"estado_recurso:{row.get('id')}",
            stop_classification=classify_state_row(row),
        ))
    return inputs


def summarize_physical_states(rows, *, inicio: datetime, fim: datetime):
    return consolidate_physical_time(build_physical_state_inputs(rows, inicio=inicio, fim=fim))


def _dt(value):
    if value is None or isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
