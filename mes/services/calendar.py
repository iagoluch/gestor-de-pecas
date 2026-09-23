"""Calendário produtivo canônico, independente da interface.

O serviço não inventa horário de intervalo. Quando o cadastro possui apenas
``minutos_intervalo`` e o recorte pega parte do turno, a disponibilidade é
marcada como parcial em vez de posicionar o intervalo arbitrariamente.

Hora extra planejada não é um segundo turno fixo: é uma janela pontual fora do
turno normal, cadastrada como exceção ``disponivel_extra`` do calendário. Quando
existe, o período integra a janela operacional planejada; quando não existe, o
mesmo período permanece fora de turno — o que muda a contabilidade de
disponibilidade, nunca a permissão de apontar.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta

from mes.analytics.intervals import merge_intervals
from mes.domain import DataAvailability, ManufacturingRules, ShiftWindowKind

PLANNED_OVERTIME_EXCEPTION_TYPE = "disponivel_extra"
UNAVAILABLE_EXCEPTION_TYPE = "indisponivel"


class CalendarService:
    def __init__(self, db, rules=None):
        self.db = db
        self.rules = rules or ManufacturingRules()
        # O calendário é imutável durante uma execução do caso de uso. O cache
        # vive somente nesta instância e evita repetir a mesma consulta de
        # turno/intervalo/exceção para cada dia e recurso auditado.
        self._turns_cache = {}
        self._intervals_cache = {}
        self._exceptions_cache = {}

    def _turns(self, resource_code):
        key = str(resource_code or "").strip().casefold()
        if key not in self._turns_cache:
            # Mesma convenção do resto da camada de serviços: um repositório
            # sem o carregador de turnos não é erro, é ausência de calendário
            # cadastrado — e aí vale a janela oficial da Manufatura.
            loader = getattr(self.db, "listar_turnos_recurso", None)
            self._turns_cache[key] = tuple(
                dict(row) for row in (loader(resource_code) or [])
            ) if callable(loader) else ()
        return self._turns_cache[key]

    def resolve_shift(self, resource_code, timestamp):
        if not isinstance(timestamp, datetime):
            raise TypeError("timestamp deve ser datetime")
        rows = self._turns(resource_code)
        for row in rows:
            for anchor in (timestamp.date(), timestamp.date() - timedelta(days=1)):
                if int(row.get("dia_semana")) != anchor.weekday():
                    continue
                start, end = self._shift_bounds(row, anchor)
                if start <= timestamp < end:
                    result = dict(row)
                    result["inicio"] = start
                    result["fim"] = end
                    intervals = self._exact_breaks(row, start, end)
                    if intervals:
                        break_seconds = sum((b_end - b_start).total_seconds() for b_start, b_end in intervals)
                        result["tempo_disponivel_segundos"] = max(
                            0.0, (end - start).total_seconds() - break_seconds
                        )
                        result["intervalos_exatos"] = True
                    else:
                        result["tempo_disponivel_segundos"] = max(
                            0.0,
                            (end - start).total_seconds()
                            - int(row.get("minutos_intervalo") or 0) * 60,
                        )
                        result["intervalos_exatos"] = False
                    return result
        return None

    def period_summary(self, resource_code, inicio, fim):
        if not isinstance(inicio, datetime) or not isinstance(fim, datetime):
            raise TypeError("inicio e fim devem ser datetime")
        if fim <= inicio:
            return {
                "recurso": resource_code,
                "inicio": inicio,
                "fim": fim,
                "tempo_disponivel_segundos": 0.0,
                "availability": DataAvailability.AVAILABLE.value,
                "janelas": [],
                "segmentos_disponiveis": [],
                "excecoes": [],
                "janelas_hora_extra": [],
                "tempo_hora_extra_planejada_segundos": 0.0,
                "reason": None,
            }

        turns = self._turns(resource_code)
        if not turns:
            return {
                "recurso": resource_code,
                "inicio": inicio,
                "fim": fim,
                "tempo_disponivel_segundos": None,
                "availability": DataAvailability.NOT_CONFIGURED.value,
                "janelas": [],
                "segmentos_disponiveis": [],
                "excecoes": [],
                "janelas_hora_extra": [],
                "tempo_hora_extra_planejada_segundos": 0.0,
                "reason": "Recurso sem calendário/turno produtivo configurado.",
            }

        windows = []
        first_day = inicio.date() - timedelta(days=1)
        last_day = fim.date()
        day = first_day
        while day <= last_day:
            for row in turns:
                if int(row.get("dia_semana")) != day.weekday():
                    continue
                shift_start, shift_end = self._shift_bounds(row, day)
                clip_start = max(shift_start, inicio)
                clip_end = min(shift_end, fim)
                if clip_end <= clip_start:
                    continue

                exact_breaks = self._exact_breaks(row, shift_start, shift_end)
                aggregate_break_seconds = max(0, int(row.get("minutos_intervalo") or 0)) * 60
                full_shift_clip = clip_start == shift_start and clip_end == shift_end

                if exact_breaks:
                    segments = [(clip_start, clip_end)]
                    for break_start, break_end in exact_breaks:
                        segments = _subtract_interval_list(segments, break_start, break_end)
                    window_total = sum((end - start).total_seconds() for start, end in segments)
                    total_exact = True
                    topology_exact = True
                elif aggregate_break_seconds:
                    # Só sabemos a duração total do intervalo, não onde ele ocorre.
                    # No turno completo o total disponível é conhecido, porém a
                    # topologia temporal continua desconhecida. Em um recorte
                    # parcial nem o total do recorte pode ser afirmado.
                    segments = []
                    topology_exact = False
                    total_exact = full_shift_clip
                    window_total = (
                        max(0.0, (clip_end - clip_start).total_seconds() - aggregate_break_seconds)
                        if total_exact
                        else None
                    )
                else:
                    segments = [(clip_start, clip_end)]
                    window_total = (clip_end - clip_start).total_seconds()
                    total_exact = True
                    topology_exact = True

                windows.append({
                    "turno_id": row.get("id"),
                    "turno": row.get("nome"),
                    "calendario_codigo": row.get("calendario_codigo"),
                    "calendario": row.get("calendario_nome"),
                    "timezone": row.get("timezone"),
                    "inicio_turno": shift_start,
                    "fim_turno": shift_end,
                    "inicio_periodo": clip_start,
                    "fim_periodo": clip_end,
                    "segmentos_disponiveis": segments,
                    "intervalos_exatos": bool(exact_breaks),
                    "topologia_exata": topology_exact,
                    "tempo_disponivel_segundos": window_total,
                    "tempo_disponivel_exato": total_exact,
                    "minutos_intervalo_agregado": int(row.get("minutos_intervalo") or 0),
                })
            day += timedelta(days=1)

        exceptions = self._exceptions(turns, inicio, fim)

        exact_segments = []
        scalar_total = 0.0
        unresolved_total = False
        unresolved_topology = False

        # Aplica exceções por janela. Em janelas com intervalo agregado e posição
        # desconhecida, qualquer exceção sobreposta torna também o total incerto,
        # pois não sabemos se a exceção coincide com o intervalo.
        for window in windows:
            clip_start = window["inicio_periodo"]
            clip_end = window["fim_periodo"]
            overlapping_exceptions = []
            for raw in exceptions:
                row = dict(raw)
                exc_start, exc_end = _exception_bounds(row)
                if exc_end > clip_start and exc_start < clip_end:
                    overlapping_exceptions.append((row, exc_start, exc_end))

            if window["topologia_exata"]:
                segments = list(window["segmentos_disponiveis"])
                for row, exc_start, exc_end in overlapping_exceptions:
                    exc_start = max(exc_start, inicio)
                    exc_end = min(exc_end, fim)
                    if exc_end <= exc_start:
                        continue
                    if str(row.get("tipo")) == "indisponivel":
                        segments = _subtract_interval_list(segments, exc_start, exc_end)
                    elif str(row.get("tipo")) == "disponivel_extra":
                        segments.append((exc_start, exc_end))
                exact_segments.extend(segments)
            else:
                unresolved_topology = True
                if not window["tempo_disponivel_exato"] or overlapping_exceptions:
                    unresolved_total = True
                else:
                    scalar_total += float(window["tempo_disponivel_segundos"] or 0.0)

        # Exceções de disponibilidade extra que estejam fora das janelas normais
        # podem ser posicionadas com exatidão e entram como segmentos adicionais.
        for raw in exceptions:
            row = dict(raw)
            if str(row.get("tipo")) != "disponivel_extra":
                continue
            exc_start, exc_end = _exception_bounds(row)
            exc_start = max(exc_start, inicio)
            exc_end = min(exc_end, fim)
            if exc_end <= exc_start:
                continue
            covered_by_window = any(
                exc_end > window["inicio_periodo"] and exc_start < window["fim_periodo"]
                for window in windows
            )
            if not covered_by_window:
                exact_segments.append((exc_start, exc_end))

        merged = merge_intervals(exact_segments)
        exact_segment_total = sum((end - start).total_seconds() for start, end in merged)
        total = None if unresolved_total else exact_segment_total + scalar_total

        if unresolved_total or unresolved_topology:
            availability = DataAvailability.PARTIAL.value
            if unresolved_total:
                reason = (
                    "Há recorte/exceção sobre turno com apenas minutos_intervalo agregado; "
                    "nem a posição nem o total disponível do recorte podem ser afirmados com segurança."
                )
            else:
                reason = (
                    "O total disponível é conhecido, mas a posição exata do intervalo do turno "
                    "não está cadastrada; a timeline de disponibilidade permanece parcial."
                )
        else:
            availability = DataAvailability.AVAILABLE.value
            reason = None

        overtime = self.planned_overtime_intervals(resource_code, inicio, fim)
        return {
            "recurso": resource_code,
            "inicio": inicio,
            "fim": fim,
            "tempo_disponivel_segundos": total,
            "availability": availability,
            "janelas": windows,
            "segmentos_disponiveis": merged,
            "excecoes": [dict(row) for row in exceptions],
            "janelas_hora_extra": overtime,
            "tempo_hora_extra_planejada_segundos": sum(
                (end - start).total_seconds() for start, end in overtime
            ),
            "reason": reason,
        }

    def available_seconds(self, resource_code, inicio, fim):
        return self.period_summary(resource_code, inicio, fim)

    # ------------------------------------------------------------------
    # Janela operacional: turno, hora extra planejada e fora de turno
    # ------------------------------------------------------------------

    def shift_intervals(self, resource_code, inicio, fim):
        """Janelas de turno cadastradas que tocam o período, sem recorte.

        O recorte é deixado para quem soma tempo. Manter a janela inteira
        permite decidir com exatidão se um instante é o fim do turno.
        """

        turns = self._turns(resource_code)
        if not turns:
            return []
        windows = []
        day = inicio.date() - timedelta(days=1)
        last_day = fim.date()
        while day <= last_day:
            for row in turns:
                if int(row.get("dia_semana")) != day.weekday():
                    continue
                start, end = self._shift_bounds(row, day)
                if end >= inicio and start <= fim:
                    windows.append((start, end))
            day += timedelta(days=1)
        return merge_intervals(windows)

    def planned_overtime_intervals(self, resource_code, inicio, fim):
        """Hora extra planejada: ``disponivel_extra`` fora das janelas de turno.

        Uma exceção de disponibilidade extra que cai dentro do próprio turno não
        é hora extra — é apenas reforço do turno normal e já está contabilizada
        como disponibilidade.
        """

        turns = self._turns(resource_code)
        shifts = self.shift_intervals(resource_code, inicio, fim)
        intervals = []
        for raw in self._exceptions(turns, inicio, fim):
            row = dict(raw)
            if str(row.get("tipo")) != PLANNED_OVERTIME_EXCEPTION_TYPE:
                continue
            exc_start, exc_end = _exception_bounds(row)
            exc_start = max(exc_start, inicio)
            exc_end = min(exc_end, fim)
            if exc_end <= exc_start:
                continue
            for piece_start, piece_end in _subtract_many([(exc_start, exc_end)], shifts):
                intervals.append((piece_start, piece_end))
        return merge_intervals(intervals)

    def operational_intervals(self, resource_code, inicio, fim):
        """Janela operacional planejada = turno + hora extra planejada.

        Exceções ``indisponivel`` recortam a janela; fora de turno simplesmente
        não faz parte dela.
        """

        turns = self._turns(resource_code)
        windows = [
            (max(start, inicio), min(end, fim))
            for start, end in self.shift_intervals(resource_code, inicio, fim)
        ]
        windows.extend(self.planned_overtime_intervals(resource_code, inicio, fim))
        merged = merge_intervals([(s, e) for s, e in windows if e > s])
        for raw in self._exceptions(turns, inicio, fim):
            row = dict(raw)
            if str(row.get("tipo")) != UNAVAILABLE_EXCEPTION_TYPE:
                continue
            exc_start, exc_end = _exception_bounds(row)
            merged = _subtract_interval_list(merged, exc_start, exc_end)
        return merge_intervals(merged)

    def out_of_shift_intervals(self, resource_code, inicio, fim):
        """Complemento da janela operacional dentro do recorte.

        Fora de turno é grandeza de calendário: não é disponibilidade e não é
        parada da máquina. Sem calendário cadastrado, a janela oficial da
        Manufatura (08:00–17:30) é a referência.
        """

        if fim <= inicio:
            return []
        operational = self.operational_intervals(resource_code, inicio, fim)
        if not operational and not self._turns(resource_code):
            operational = _official_window_intervals(
                inicio, fim, self.rules.official_work_window
            )
        return _subtract_many([(inicio, fim)], operational)

    def shift_window_kind(self, resource_code, timestamp):
        """Classifica o instante para o recurso, usando o cadastro quando existe."""

        if not isinstance(timestamp, datetime):
            raise TypeError("timestamp deve ser datetime")
        turns = self._turns(resource_code)
        window_start = timestamp - timedelta(days=1)
        window_end = timestamp + timedelta(days=1)
        if turns:
            for start, end in self.shift_intervals(resource_code, window_start, window_end):
                if start <= timestamp <= end:
                    return ShiftWindowKind.OFFICIAL_SHIFT
        for start, end in self.planned_overtime_intervals(
            resource_code, window_start, window_end
        ):
            if start <= timestamp <= end:
                return ShiftWindowKind.PLANNED_OVERTIME
        if turns:
            return ShiftWindowKind.OUT_OF_SHIFT
        return ManufacturingRules.shift_window_kind(
            timestamp,
            planned_overtime_windows=self.rules.overtime_windows,
            official_work_window=self.rules.official_work_window,
        )

    def _exceptions(self, turns, inicio, fim):
        calendar_codes = {
            str(row.get("calendario_codigo") or "").strip()
            for row in turns if str(row.get("calendario_codigo") or "").strip()
        }
        exceptions = []
        loader = getattr(self.db, "listar_excecoes_calendario_periodo", None)
        if not callable(loader):
            return exceptions
        for code in sorted(calendar_codes):
            key = (code.casefold(), inicio, fim)
            if key not in self._exceptions_cache:
                self._exceptions_cache[key] = tuple(
                    dict(row) for row in (loader(code, inicio, fim) or [])
                )
            exceptions.extend(self._exceptions_cache[key])
        return exceptions

    @staticmethod
    def _shift_bounds(row, anchor):
        start = datetime.combine(anchor, row["hora_inicio"])
        end = datetime.combine(anchor, row["hora_fim"])
        if bool(row.get("cruza_meia_noite")) or end <= start:
            end += timedelta(days=1)
        return start, end

    def _exact_breaks(self, row, shift_start, shift_end):
        loader = getattr(self.db, "listar_intervalos_turno", None)
        if not callable(loader) or row.get("id") is None:
            return []
        shift_id = row["id"]
        if shift_id not in self._intervals_cache:
            self._intervals_cache[shift_id] = tuple(
                dict(interval) for interval in (loader(shift_id) or [])
            )
        result = []
        for interval in self._intervals_cache[shift_id]:
            if not interval.get("desconta_tempo", True):
                continue
            start = datetime.combine(shift_start.date(), interval["hora_inicio"])
            end = datetime.combine(shift_start.date(), interval["hora_fim"])
            if end <= start:
                end += timedelta(days=1)
            # Se o turno cruza meia-noite e o intervalo é claramente no dia
            # seguinte, desloca o intervalo para dentro da janela do turno.
            if start < shift_start and shift_end.date() > shift_start.date():
                start += timedelta(days=1)
                end += timedelta(days=1)
            start = max(start, shift_start)
            end = min(end, shift_end)
            if end > start:
                result.append((start, end))
        return merge_intervals(result)


def _exception_bounds(row):
    day = row["data"]
    start_time = row.get("hora_inicio")
    end_time = row.get("hora_fim")
    if start_time is None and end_time is None:
        start = datetime.combine(day, time.min)
        end = start + timedelta(days=1)
        return start, end
    start = datetime.combine(day, start_time)
    end = datetime.combine(day, end_time)
    if end <= start:
        end += timedelta(days=1)
    return start, end


def _official_window_intervals(inicio, fim, official_work_window=None):
    """Janela oficial da Manufatura para recursos ainda sem calendário."""

    start_time, end_time = official_work_window or ManufacturingRules.official_work_window
    intervals = []
    day = inicio.date() - timedelta(days=1)
    last_day = fim.date()
    while day <= last_day:
        start = datetime.combine(day, start_time)
        end = datetime.combine(day, end_time)
        if end <= start:
            end += timedelta(days=1)
        start = max(start, inicio)
        end = min(end, fim)
        if end > start:
            intervals.append((start, end))
        day += timedelta(days=1)
    return merge_intervals(intervals)


def _subtract_many(intervals, cuts):
    result = list(intervals)
    for cut_start, cut_end in cuts:
        result = _subtract_interval_list(result, cut_start, cut_end)
    return result


def _subtract_interval_list(intervals, cut_start, cut_end):
    result = []
    for start, end in intervals:
        if cut_end <= start or cut_start >= end:
            result.append((start, end))
            continue
        if cut_start > start:
            result.append((start, min(cut_start, end)))
        if cut_end < end:
            result.append((max(cut_end, start), end))
    return [(start, end) for start, end in result if end > start]


