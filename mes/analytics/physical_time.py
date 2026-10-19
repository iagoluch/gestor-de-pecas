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
from typing import Iterable, Literal, Mapping

from app.core.resource_mapping import resolve_resource_identity
from mes.analytics.intervals import merge_intervals
from mes.domain import EventCategory, StopClassification


# Regra aplicada quando mais de uma fonte disputa o mesmo instante. ``None``
# significa que nenhuma decisão foi necessária (fonte única ou fontes em acordo).
Rule = Literal["production_prevailed", "state_conflict", "reclassified_to_unplanned"]


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
    # Proveniência (explicação clicável): fontes ativas no intervalo e a regra
    # aplicada. Não entram em nenhum total.
    source_refs: tuple[str | int, ...] = ()
    rule: Rule | None = None

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
        # Identidade canônica: alias ("Laser Ensis 3015") e código ("LASER1")
        # são o mesmo recurso físico e não podem virar dois grupos.
        resource_key = (
            str(resolve_resource_identity(segment.resource) or "").strip().casefold()
        )
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
    by_sector_stop = defaultdict(lambda: defaultdict(lambda: defaultdict(float)))
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
            by_sector_stop[segment.sector][segment.category][
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
        "by_sector_stop_classification": {
            sector: {
                category: dict(value) for category, value in categories.items()
            }
            for sector, categories in by_sector_stop.items()
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


def restrict_to_resources(consolidated: Mapping, resources: Iterable[str]) -> dict:
    """Recorte de uma consolidação a um conjunto de recursos (visão, não regra).

    Devolve uma cópia com ``segments``, ``totals``, ``totals_by_stop_classification``,
    ``conflicting_state_seconds``, ``physical_seconds`` e
    ``out_of_shift_attributed_seconds`` recalculados só para ``resources``. O total
    de fora de turno (união global de calendário) é preservado: ele não pertence a
    nenhum recurso em particular. A consolidação original não é alterada.
    """

    wanted = {str(name) for name in resources}
    kept = tuple(seg for seg in consolidated["segments"] if seg.resource in wanted)
    totals: dict = defaultdict(float)
    stop_totals: dict = defaultdict(lambda: defaultdict(float))
    out_attributed = 0.0
    conflict = 0.0
    for seg in kept:
        totals[seg.category] += seg.seconds
        if seg.stop_classification is not None:
            stop_totals[seg.category][seg.stop_classification] += seg.seconds
        if seg.category is EventCategory.OUT_OF_SHIFT:
            out_attributed += seg.seconds
        if seg.state_conflict:
            conflict += seg.seconds
    original_totals = consolidated.get("totals") or {}
    if EventCategory.OUT_OF_SHIFT in original_totals:
        totals[EventCategory.OUT_OF_SHIFT] = original_totals[EventCategory.OUT_OF_SHIFT]
    return {
        **consolidated,
        "segments": kept,
        "totals": dict(totals),
        "totals_by_stop_classification": {
            category: dict(value) for category, value in stop_totals.items()
        },
        "conflicting_state_seconds": conflict,
        "physical_seconds": sum(seg.seconds for seg in kept),
        "out_of_shift_attributed_seconds": out_attributed,
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

            # Produção prevalece sobre parada (decisão do usuário, 01/10/2026):
            # com uma OP produzindo, o recurso está produzindo, mesmo que outra
            # OP dele esteja parada. Só é parada quando todas as fontes param.
            classified = active_segments
            production_prevailed = False
            if categories == {EventCategory.PRODUCTION, EventCategory.DOWNTIME}:
                categories = {EventCategory.PRODUCTION}
                production_prevailed = True
                classified = [
                    segment for segment in active_segments
                    if segment.category is EventCategory.PRODUCTION
                ]
            state_conflict = len(categories) > 1
            sector_conflict = len(sectors) > 1
            category = next(iter(categories)) if not state_conflict else EventCategory.UNKNOWN
            sector = next(iter(sectors)) if not sector_conflict else "Não informado"
            resource = _display_resource(active_segments)
            classification, reclassified = (
                (None, False) if state_conflict
                else _resolve_stop_classification(classified)
            )
            rule = _applied_rule(
                state_conflict=state_conflict,
                reclassified=reclassified,
                production_prevailed=production_prevailed,
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
                source_refs=_source_refs(active_segments),
                rule=rule,
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

    Retorna ``(classificação, reclassificada)``; ``reclassificada`` é verdadeiro
    só quando a divergência forçou ``UNPLANNED``.
    """

    values = {
        segment.stop_classification
        for segment in active_segments
        if segment.stop_classification is not None
    }
    if not values:
        return None, False
    if len(values) == 1:
        return next(iter(values)), False
    return StopClassification.UNPLANNED, True


def _applied_rule(*, state_conflict, reclassified, production_prevailed):
    """Regra que de fato decidiu o intervalo (a mais consequente vence)."""

    if state_conflict:
        return "state_conflict"
    if reclassified:
        return "reclassified_to_unplanned"
    if production_prevailed:
        return "production_prevailed"
    return None


def _source_refs(active_segments):
    """Origens (sem ``None``, sem repetição) ordenadas de forma estável."""

    refs = {
        segment.source_ref for segment in active_segments
        if segment.source_ref is not None
    }
    return tuple(sorted(refs, key=lambda ref: (isinstance(ref, str), str(ref))))


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
