"""Decomposição temporal de apontamentos em estados industriais."""

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, Mapping, Optional

from mes.domain import EventCategory


_STATE_MAP = {
    "fila": EventCategory.QUEUE,
    "producao": EventCategory.PRODUCTION,
    "produção": EventCategory.PRODUCTION,
    "parada": EventCategory.DOWNTIME,
    "setup": EventCategory.SETUP,
    "retrabalho": EventCategory.REWORK,
    "fora_turno": EventCategory.OUT_OF_SHIFT,
}
_NON_STATE_EVENTS = {"parcial", "finalizado"}


@dataclass(frozen=True)
class TimelineSegment:
    category: EventCategory
    start: datetime
    end: datetime
    seconds: float
    source_event_id: Optional[int] = None
    status_code: Optional[str] = None
    reason: Optional[str] = None
    planned: bool = False
    automatic: bool = False
    interruption_type: Optional[str] = None


@dataclass(frozen=True)
class TimelineResult:
    segments: tuple[TimelineSegment, ...]
    totals: Mapping[EventCategory, float]
    physical_seconds: float
    has_event_data: bool

    def seconds(self, category: EventCategory) -> float:
        return float(self.totals.get(category, 0.0))


def _as_datetime(value):
    if value is None or isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def _state(value):
    text = str(value or "").strip().casefold()
    return _STATE_MAP.get(text)


def build_operator_timeline(
    events: Iterable[Mapping],
    *,
    start: datetime,
    end: datetime,
    initial_category: EventCategory = EventCategory.PRODUCTION,
) -> TimelineResult:
    """Converte transições em segmentos recortados ao período solicitado.

    Eventos ``parcial`` são fatos de quantidade e não alteram o estado físico.
    ``finalizado`` encerra a linha do tempo, sem criar um estado próprio.
    """

    if end < start:
        raise ValueError("O fim da timeline não pode ser anterior ao início.")

    normalized = []
    for raw in events or ():
        timestamp = _as_datetime(raw.get("data_hora"))
        if timestamp is None:
            continue
        normalized.append((timestamp, int(raw.get("id") or 0), dict(raw)))
    normalized.sort(key=lambda item: (item[0], item[1]))

    current = initial_category
    current_start = start
    current_event = None
    segments = []
    has_state_data = False

    # Determina o estado vigente no início do recorte usando eventos anteriores.
    for timestamp, _order, raw in normalized:
        if timestamp > start:
            break
        state_text = str(raw.get("estado") or "").strip().casefold()
        mapped = _state(state_text)
        if mapped is not None:
            current = mapped
            current_event = raw
            has_state_data = True
        elif state_text == "finalizado":
            current_start = start

    for timestamp, _order, raw in normalized:
        if timestamp <= start:
            continue
        if timestamp > end:
            break
        state_text = str(raw.get("estado") or "").strip().casefold()
        if state_text in _NON_STATE_EVENTS:
            if state_text == "finalizado":
                if timestamp > current_start:
                    segments.append(_segment(current, current_start, timestamp, current_event))
                current_start = timestamp
                break
            continue
        mapped = _state(state_text)
        if mapped is None:
            continue
        has_state_data = True
        if timestamp > current_start:
            segments.append(_segment(current, current_start, timestamp, current_event))
        current = mapped
        current_start = timestamp
        current_event = raw
    else:
        if current_start < end:
            segments.append(_segment(current, current_start, end, current_event))

    # Se o loop terminou por finalização, não estende depois do evento terminal.
    totals = {category: 0.0 for category in EventCategory}
    for segment in segments:
        totals[segment.category] = totals.get(segment.category, 0.0) + segment.seconds
    physical = sum(segment.seconds for segment in segments)
    return TimelineResult(tuple(segments), totals, physical, has_state_data)


def _segment(category, start, end, raw):
    return TimelineSegment(
        category=category,
        start=start,
        end=end,
        seconds=max(0.0, (end - start).total_seconds()),
        source_event_id=int(raw.get("id") or 0) or None if raw else None,
        status_code=(raw.get("codigo_status_recurso") if raw else None),
        reason=(raw.get("motivo") if raw else None),
        planned=bool(raw.get("interrupcao_programada")) if raw else False,
        automatic=bool(raw.get("origem_automatica")) if raw else False,
        interruption_type=(raw.get("tipo_interrupcao") if raw else None),
    )
