"""Consolidação de tempo físico por recurso sem duplicar OPs simultâneas.

Uma mesma máquina pode executar mais de uma OP no mesmo intervalo. As timelines
por OP são fatos atribuídos e, se forem somadas diretamente, inflam o tempo físico
do recurso. Este módulo faz uma varredura temporal por recurso e mantém uma única
classificação física por instante.

Quando duas timelines do mesmo recurso concordam no estado (por exemplo, duas OPs
em ``produção``), o intervalo é contabilizado uma única vez. Quando estados físicos
diferentes se sobrepõem, o sistema não escolhe silenciosamente qual deles é
"correto": o período vai para ``desconhecido`` e é marcado como conflito de dados.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, Mapping

from mes.analytics.intervals import merge_intervals
from mes.domain import EventCategory, StopClassification


@dataclass(frozen=True)
class PhysicalInputSegment:
    resource: str
    sector: str
    category: EventCategory
    start: datetime
    end: datetime
    source_ref: str | int | None = None
    stop_classification: StopClassification | None = None

    @property
    def seconds(self) -> float:
        return max(0.0, (self.end - self.start).total_seconds())


@dataclass(frozen=True)
class PhysicalConsolidatedSegment:
    resource: str
    sector: str
    category: EventCategory
    start: datetime
    end: datetime
    active_sources: int
    state_conflict: bool = False
    sector_conflict: bool = False
    stop_classification: StopClassification | None = None

    @property
    def seconds(self) -> float:
        return max(0.0, (self.end - self.start).total_seconds())


def consolidate_physical_time(
    segments: Iterable[PhysicalInputSegment | Mapping],
) -> dict:
    """Consolida timelines atribuídas em tempo físico de recurso.

    Retorna totais físicos, tempo bruto atribuído, sobreposição removida e os
    intervalos conflitantes. O total físico é sempre a união temporal por recurso;
    portanto duas OPs simultâneas na mesma máquina nunca criam horas artificiais.
    """

    normalized = []
    for index, raw in enumerate(segments or ()):
        item = _normalize(raw, index)
        if item is not None and item.end > item.start:
            normalized.append(item)

    by_group = defaultdict(list)
    raw_attributed = 0.0
    for index, segment in enumerate(normalized):
        raw_attributed += segment.seconds
        # Sem código de recurso não podemos assumir que dois fatos são da mesma
        # máquina. Usa uma chave isolada para não colapsar recursos desconhecidos.
        resource_key = segment.resource.strip().casefold()
        if not resource_key or resource_key == "não informado".casefold():
            resource_key = f"__recurso_desconhecido__:{segment.source_ref!s}:{index}"
        by_group[resource_key].append(segment)

    consolidated = []
    for group in by_group.values():
        consolidated.extend(_sweep_resource(group))

    totals = defaultdict(float)
    by_resource = defaultdict(lambda: defaultdict(float))
    by_sector = defaultdict(lambda: defaultdict(float))
    stop_totals = defaultdict(lambda: defaultdict(float))
    by_resource_stop = defaultdict(lambda: defaultdict(lambda: defaultdict(float)))
    physical_seconds = 0.0
    overlap_seconds = 0.0
    conflict_seconds = 0.0
    sector_conflict_seconds = 0.0
    out_of_shift_intervals = []

    for segment in consolidated:
        seconds = segment.seconds
        physical_seconds += seconds
        totals[segment.category] += seconds
        by_resource[segment.resource][segment.category] += seconds
        by_sector[segment.sector][segment.category] += seconds
        if segment.stop_classification is not None:
            stop_totals[segment.category][segment.stop_classification] += seconds
            by_resource_stop[segment.resource][segment.category][
                segment.stop_classification
            ] += seconds
        if segment.category is EventCategory.OUT_OF_SHIFT:
            out_of_shift_intervals.append((segment.start, segment.end))
        if segment.active_sources > 1:
            overlap_seconds += seconds
        if segment.state_conflict:
            conflict_seconds += seconds
        if segment.sector_conflict:
            sector_conflict_seconds += seconds

    # Fora de turno é uma grandeza global de calendário: o mesmo intervalo
    # noturno observado em vários recursos/setores é o MESMO intervalo. O total
    # global usa a união temporal; ``by_resource``/``by_sector`` preservam a
    # leitura por recurso, que continua correta no seu próprio escopo.
    attributed_out_of_shift = totals.get(EventCategory.OUT_OF_SHIFT, 0.0)
    global_out_of_shift = sum(
        (end - start).total_seconds()
        for start, end in merge_intervals(out_of_shift_intervals)
    )
    if out_of_shift_intervals:
        totals[EventCategory.OUT_OF_SHIFT] = global_out_of_shift

    return {
        "segments": tuple(consolidated),
        "totals": dict(totals),
        "by_resource": {key: dict(value) for key, value in by_resource.items()},
        "by_sector": {key: dict(value) for key, value in by_sector.items()},
        # {EventCategory: {StopClassification: segundos}} — a classificação é
        # central e vale por categoria física, não por componente visual.
        "totals_by_stop_classification": {
            category: dict(value) for category, value in stop_totals.items()
        },
        "by_resource_stop_classification": {
            resource: {
                category: dict(value) for category, value in categories.items()
            }
            for resource, categories in by_resource_stop.items()
        },
        "physical_seconds": physical_seconds,
        "raw_attributed_seconds": raw_attributed,
        "overlap_removed_seconds": max(0.0, raw_attributed - physical_seconds),
        "overlap_seconds": overlap_seconds,
        "conflicting_state_seconds": conflict_seconds,
        "conflicting_sector_seconds": sector_conflict_seconds,
        "out_of_shift_global_seconds": global_out_of_shift,
        "out_of_shift_attributed_seconds": attributed_out_of_shift,
        "out_of_shift_duplicated_seconds": max(
            0.0, attributed_out_of_shift - global_out_of_shift
        ),
    }


def _normalize(raw, index):
    if isinstance(raw, PhysicalInputSegment):
        return raw
    if not isinstance(raw, Mapping):
        return None
    start = _dt(raw.get("start") or raw.get("inicio"))
    end = _dt(raw.get("end") or raw.get("fim"))
    if start is None or end is None:
        return None
    try:
        category = raw.get("category") or raw.get("categoria")
        category = category if isinstance(category, EventCategory) else EventCategory(str(category))
    except (TypeError, ValueError):
        category = EventCategory.UNKNOWN
    raw_classification = raw.get("stop_classification", raw.get("classificacao_parada"))
    try:
        classification = (
            StopClassification(raw_classification)
            if raw_classification is not None
            else None
        )
    except (TypeError, ValueError):
        classification = None
    return PhysicalInputSegment(
        resource=str(raw.get("resource") or raw.get("recurso") or "Não informado").strip() or "Não informado",
        sector=str(raw.get("sector") or raw.get("setor") or "Não informado").strip() or "Não informado",
        category=category,
        start=start,
        end=end,
        source_ref=raw.get("source_ref", raw.get("fonte", index)),
        stop_classification=classification,
    )


def _sweep_resource(group):
    events = []
    indexed = list(enumerate(group))
    for index, segment in indexed:
        # Fim antes do início no mesmo timestamp evita intervalo artificial e
        # permite transições contíguas sem falsa concorrência.
        events.append((segment.start, 1, index))
        events.append((segment.end, 0, index))
    events.sort(key=lambda item: (item[0], item[1]))

    active = set()
    result = []
    previous = None
    cursor = 0

    while cursor < len(events):
        timestamp = events[cursor][0]
        if previous is not None and timestamp > previous and active:
            active_segments = [group[index] for index in sorted(active)]
            categories = {segment.category for segment in active_segments}
            sectors = {segment.sector for segment in active_segments}

            state_conflict = len(categories) > 1
            sector_conflict = len(sectors) > 1
            category = next(iter(categories)) if not state_conflict else EventCategory.UNKNOWN
            sector = next(iter(sectors)) if not sector_conflict else "Não informado"
            resource = _display_resource(active_segments)
            classification = (
                None if state_conflict
                else _resolve_stop_classification(active_segments)
            )

            result.append(PhysicalConsolidatedSegment(
                resource=resource,
                sector=sector,
                category=category,
                start=previous,
                end=timestamp,
                active_sources=len(active_segments),
                state_conflict=state_conflict,
                sector_conflict=sector_conflict,
                stop_classification=classification,
            ))

        # Processa todos os eventos do mesmo instante em conjunto.
        same_time = []
        while cursor < len(events) and events[cursor][0] == timestamp:
            same_time.append(events[cursor])
            cursor += 1
        for _time, kind, index in same_time:
            if kind == 0:
                active.discard(index)
        for _time, kind, index in same_time:
            if kind == 1:
                active.add(index)
        previous = timestamp

    return result


def _resolve_stop_classification(active_segments):
    """Classificação vigente no instante consolidado.

    Quando duas fontes concordam, o valor é preservado. Quando divergem sobre o
    mesmo estado físico, o instante é tratado como não planejado: o sistema não
    esconde perda operacional atrás da classificação mais favorável.
    """

    values = {
        segment.stop_classification
        for segment in active_segments
        if segment.stop_classification is not None
    }
    if not values:
        return None
    if len(values) == 1:
        return next(iter(values))
    return StopClassification.UNPLANNED


def _display_resource(active_segments):
    resources = {
        segment.resource for segment in active_segments
        if segment.resource and segment.resource.casefold() != "não informado".casefold()
    }
    if len(resources) == 1:
        return next(iter(resources))
    return "Não informado"


def _dt(value):
    if value is None or isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
