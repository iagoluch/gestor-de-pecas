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


def physical_state_category(row) -> EventCategory:
    """Categoria analítica de um estado físico persistido.

    ``sem_demanda`` não existe na base: é derivada aqui, uma única vez, a
    partir de toda ``fila`` sem OP. Assim Andon, análises e exportações usam a
    mesma verdade sem depender do processo que gravou o estado físico.
    """

    row = dict(row or {})
    try:
        category = EventCategory(str(row.get("categoria") or ""))
    except ValueError:
        return EventCategory.UNKNOWN
    if ManufacturingRules.state_is_no_demand(
        category=category,
        interruption_type=row.get("tipo_interrupcao"),
        operation=row.get("op"),
    ):
        return EventCategory.NO_DEMAND
    return category


#: Ociosidade que só conta dentro do turno configurado em ``parametros_turno``.
SHIFT_BOUND_IDLE_CATEGORIES = (EventCategory.NO_DEMAND, EventCategory.QUEUE)


def build_physical_state_inputs(rows, *, inicio: datetime, fim: datetime, calendar=None):
    """Segmentos físicos dos estados persistidos.

    Com ``calendar`` (``CalendarService``), a ociosidade (sem demanda e fila)
    que passa dos limites do turno vira ``fora_turno``: um estado aberto não
    pode estender "recurso sem demanda" madrugada adentro quando o fim do
    turno ainda não foi gravado pelo agendador.
    """

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
        category = physical_state_category(row)
        resource = str(row.get("recurso") or "Não informado").strip() or "Não informado"
        pieces = [(start, end, category)]
        if calendar is not None and category in SHIFT_BOUND_IDLE_CATEGORIES:
            pieces = _split_by_shift(calendar, resource, start, end, category)
        for piece_start, piece_end, piece_category in pieces:
            inputs.append(PhysicalInputSegment(
                resource=resource,
                sector=str(row.get("tipo_setor") or "Não informado").strip() or "Não informado",
                category=piece_category,
                start=piece_start,
                end=piece_end,
                source_ref=f"estado_recurso:{row.get('id')}",
                stop_classification=classify_state_row(row) if piece_category is category else None,
            ))
    return inputs


def _split_by_shift(calendar, resource, start, end, category):
    """Divide ``[start, end)`` em trecho dentro do turno (``category``) e fora dele."""

    outside = [
        (max(a, start), min(b, end))
        for a, b in calendar.out_of_shift_intervals(resource, start, end)
        if min(b, end) > max(a, start)
    ]
    pieces = [(a, b, EventCategory.OUT_OF_SHIFT) for a, b in outside]
    cursor = start
    for a, b in sorted(outside):
        if a > cursor:
            pieces.append((cursor, a, category))
        cursor = max(cursor, b)
    if end > cursor:
        pieces.append((cursor, end, category))
    return sorted(pieces, key=lambda piece: piece[0])


def summarize_physical_states(rows, *, inicio: datetime, fim: datetime, calendar=None):
    return consolidate_physical_time(
        build_physical_state_inputs(rows, inicio=inicio, fim=fim, calendar=calendar)
    )


def _dt(value):
    if value is None or isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
