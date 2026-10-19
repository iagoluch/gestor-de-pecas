"""Resumo da aba Diretoria: Painel, Ficha e Custos (16/10/2026).

Fonte única: horas, peças e OEE vêm de ``ManagementService.get_overview`` e
as paradas de ``IndustrialAnalyticsService.downtimes`` com o mesmo filtro da
Visão Geral. Este módulo só cruza esses números com os valores por hora
(``mes.domain.director_cost``) e escreve o texto em linguagem simples.
Nenhuma regra de OEE, turno ou parada é recalculada aqui.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import replace
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from app.core.operator_sectors import OPERATOR_SECTORS
from app.core.resource_mapping import STATION_RESOURCE_CODES, resolve_resource_identity, resource_display_name
from mes.analytics.oee import _WORKED_CATEGORIES
from mes.analytics.physical_time import consolidate_physical_time
from mes.analytics.resource_state import classify_state_row
from mes.contracts import AnalyticsFilter
from mes.domain import EventCategory, ManufacturingRules, StopClassification
from mes.domain.director_cost import CostRates, CostResult, StopSlice, stop_cost, work_cost
from mes.services.display_labels import strip_status_code_prefix
from mes.services.industrial_analytics import IndustrialAnalyticsService

PERIODS = ("hoje", "semana", "mes")
_CENTAVO = Decimal("0.01")
_UNKNOWN_RESOURCE = "NÃO INFORMADO"
_TOP_LOSSES = 3
_MAX_RATE = Decimal(10) ** 10


class DirectorSummaryError(Exception):
    """Violação de regra com código estável; a rota converte em ``AppError``."""

    def __init__(self, code: str, message: str, status_code: int = 422, details=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details


# --------------------------------------------------------------------------- período

def resolve_period(name, now: datetime) -> tuple[datetime, datetime]:
    """Período nomeado → (início, fim), no mesmo recorte da Visão Geral.

    "hoje" é o dia civil (00:00:00–23:59:59), igual ao filtro "Hoje" da Visão
    Geral; "semana" começa na segunda-feira; "mes" no dia 1. O fim é sempre o
    fim do dia de hoje: o banco já corta estados abertos em "agora".
    """
    key = normalize_period(name)
    if key not in PERIODS:
        raise DirectorSummaryError(
            "INVALID_PERIOD",
            "Período inválido: use hoje, semana ou mes.",
            status_code=422,
            details={"periodo": name, "aceitos": list(PERIODS)},
        )
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end = today.replace(hour=23, minute=59, second=59)
    if key == "hoje":
        return today, end
    if key == "semana":
        return today - timedelta(days=today.weekday()), end
    return today.replace(day=1), end


def normalize_period(name) -> str:
    return str(name or "").strip().casefold()


# --------------------------------------------------------------------------- formatação

def format_hours(hours) -> str:
    value = round(float(hours or 0.0), 1)
    if value == int(value):
        return f"{int(value)} h"
    return f"{value:.1f}".replace(".", ",") + " h"


def format_reais(value) -> str:
    amount = Decimal(str(value or 0)).quantize(_CENTAVO, rounding=ROUND_HALF_UP)
    whole = int(amount)
    text = f"{whole:,}".replace(",", ".")
    cents = int((amount - whole) * 100)
    if cents:
        text += f",{cents:02d}"
    return f"R$ {text}"


def _missing_warning(count: int) -> str:
    return f"faltam custos de {count} recursos/pessoas — o valor real é maior"


# --------------------------------------------------------------------------- melhor/pior

def best_and_worst_sector(sector_kpis):
    """Melhor e pior setor pelo OEE já calculado na Visão Geral."""
    ranked = []
    for item in sector_kpis or ():
        oee = ((item.get("metrics") or {}).get("oee") or {}).get("value")
        if oee is None:
            continue
        ranked.append({"nome": item.get("setor"), "oee": oee})
    if not ranked:
        return None, None
    best = max(ranked, key=lambda entry: entry["oee"])
    worst = min(ranked, key=lambda entry: entry["oee"])
    if worst["oee"] == best["oee"]:
        # Setor único ou empate total: não existe "pior" de verdade.
        return best, None
    return best, worst


# --------------------------------------------------------------------------- serviço

class DirectorSummaryService:
    def __init__(self, db):
        self.db = db

    # ----------------------------------------------------------------- Painel
    def panel(self, period, now: datetime) -> dict:
        inicio, fim = resolve_period(period, now)
        ctx = _Context(self.db, AnalyticsFilter(inicio, fim), now)
        overview = ctx.overview
        hours = overview.get("hours") or {}

        stop_slices = ctx.stop_slices()
        total_stop = stop_cost(stop_slices, ctx.rates)

        sector_planned = {
            item.get("setor"): float(item.get("parada_planejada_segundos") or 0.0)
            for item in overview.get("sector_kpis") or ()
        }
        losses = []
        for sector in overview.get("sectors") or ():
            name = sector.get("setor")
            seconds = float(sector.get("tempo_parada_segundos") or 0.0) - sector_planned.get(name, 0.0)
            if seconds <= 0:
                continue
            sector_cost = stop_cost(
                [s for s in stop_slices if ctx.resource_sector.get(s.recurso) == name], ctx.rates
            )
            reasons = ctx.reasons(name)
            losses.append({
                "setor": name,
                "horas_paradas": seconds / 3600.0,
                "custo": _money(sector_cost.custo),
                "motivo_principal": reasons[0]["motivo"] if reasons else None,
                "custo_completo": sector_cost.completo,
            })
        losses.sort(key=lambda item: (-item["horas_paradas"], str(item["setor"]).casefold()))

        best, worst = best_and_worst_sector(overview.get("sector_kpis"))
        missing = _missing_count(total_stop)
        return {
            "periodo": {"nome": normalize_period(period), "inicio": inicio.isoformat(), "fim": fim.isoformat()},
            "cards": {
                "produzido": (overview.get("production") or {}).get("good", 0),
                "horas_paradas": _unplanned_stop_hours(hours),
                "custo_parada": _money(total_stop.custo),
                "eficiencia_oee": (overview.get("kpis") or {}).get("oee"),
            },
            "onde_perdemos": losses[:_TOP_LOSSES],
            "melhor_setor": best,
            "pior_setor": worst,
            "custo_completo": total_stop.completo,
            "custos_faltando": missing,
            "aviso": _missing_warning(missing) if missing else None,
        }

    # ----------------------------------------------------------------- Ficha
    def sheet(self, period, setor, recurso, now: datetime) -> dict:
        inicio, fim = resolve_period(period, now)
        setor = str(setor or "").strip() or None
        recurso = str(recurso or "").strip() or None
        ctx = _Context(self.db, AnalyticsFilter(inicio, fim, setor=setor, recurso=recurso), now)
        overview = ctx.overview
        hours = overview.get("hours") or {}
        bases = overview.get("kpi_time_bases") or {}

        stop_slices = ctx.stop_slices()
        work_slices = ctx.work_slices()
        stop_result = stop_cost(stop_slices, ctx.rates)
        work_result = work_cost(work_slices, ctx.rates)
        stop_missing = _missing_keys(stop_result)
        work_missing = _missing_keys(work_result)
        missing = len(stop_missing | work_missing)

        worked_h = float(bases.get("worked_seconds") or 0.0) / 3600.0
        available_h = float(bases.get("available_seconds") or 0.0) / 3600.0
        stopped_h = _unplanned_stop_hours(hours)
        produced = (overview.get("production") or {}).get("good", 0)
        reasons = ctx.reasons()
        main_reason = reasons[0] if reasons else None

        text = _sheet_text(
            subject=self._subject(overview, setor, recurso),
            worked_h=worked_h,
            available_h=available_h,
            produced=produced,
            stopped_h=stopped_h,
            stop_cost_value=stop_result.custo,
            main_reason=main_reason,
            missing=len(stop_missing),
            feminine=not setor and not recurso,
        )
        return {
            "texto": text,
            "trabalhou_h": worked_h,
            "disponivel_h": available_h,
            "produzido": produced,
            "custo_trabalho": _money(work_result.custo),
            "parado_h": stopped_h,
            "custo_parada": _money(stop_result.custo),
            "motivo_principal": main_reason["motivo"] if main_reason else None,
            "paradas_por_motivo": reasons,
            "sem_demanda_h": float(hours.get("no_demand_seconds") or 0.0) / 3600.0,
            "fora_turno_h": float(hours.get("out_of_shift_seconds") or 0.0) / 3600.0,
            "pessoas": ctx.people(list(work_slices) + list(stop_slices)),
            "custo_parada_completo": not stop_missing,
            "custos_faltando_parada": len(stop_missing),
            "custo_trabalho_completo": not work_missing,
            "custos_faltando_trabalho": len(work_missing),
            "custo_completo": missing == 0,
            "custos_faltando": missing,
        }

    def _subject(self, overview, setor, recurso):
        if recurso:
            sector = setor
            for item in overview.get("resource_kpis") or ():
                if _resource_key(item.get("resource")) == _resource_key(recurso):
                    sector = sector or item.get("sector") or item.get("setor")
                    break
            sector = sector or _catalog_sector(_resource_key(recurso))
            label = _resource_key(recurso)
            return f"O {label} ({sector})" if sector else f"O {label}"
        if setor:
            return f"O setor {setor}"
        return "A fábrica"

    # ----------------------------------------------------------------- Custos
    def costs(self) -> dict:
        resource_rates = {
            _resource_key(row.get("recurso")): _decimal_or_none(row.get("valor_hora"))
            for row in _call(self.db, "listar_custos_hora_recurso")
        }
        recursos = []
        seen = set()
        for key, sector in _resource_catalog():
            seen.add(key)
            recursos.append({"recurso": key, "nome": resource_display_name(key), "setor": sector, "valor_hora": _float_or_none(resource_rates.get(key))})
        for key in sorted(set(resource_rates) - seen - {""}):
            recursos.append({"recurso": key, "nome": resource_display_name(key), "setor": None, "valor_hora": _float_or_none(resource_rates[key])})

        operator_rates = {
            int(row.get("operador_id")): _decimal_or_none(row.get("valor_hora"))
            for row in _call(self.db, "listar_custos_hora_operador")
            if row.get("operador_id") is not None
        }
        pessoas = []
        for row in _call(self.db, "listar_operadores_apontamento", somente_ativos=False):
            operator_id = row.get("id")
            if operator_id is None:
                continue
            operator_id = int(operator_id)
            if not row.get("ativo", True) and operator_id not in operator_rates:
                continue
            pessoas.append({
                "operador_id": operator_id,
                "nome": row.get("nome"),
                "cracha": row.get("cracha"),
                "valor_hora": _float_or_none(operator_rates.get(operator_id)),
            })
        pessoas.sort(key=lambda item: str(item["nome"] or "").casefold())
        return {"recursos": recursos, "pessoas": pessoas}

    def set_resource_rate(self, recurso, valor, usuario):
        key = _resource_key(recurso)
        if not key:
            raise DirectorSummaryError("COST_RATE_INVALID", "Informe o recurso.", status_code=422)
        self.db.salvar_custo_hora_recurso(key, _positive_rate(valor), usuario)

    def set_operator_rate(self, operador_id, valor, usuario):
        rate = _positive_rate(valor)
        known = {
            str(row.get("id"))
            for row in _call(self.db, "listar_operadores_apontamento", somente_ativos=False)
        }
        if str(operador_id).strip() not in known:
            raise DirectorSummaryError(
                "OPERATOR_NOT_FOUND",
                "Operador não encontrado.",
                status_code=404,
                details={"operador_id": str(operador_id)},
            )
        self.db.salvar_custo_hora_operador(int(operador_id), rate, usuario)


# --------------------------------------------------------------------------- contexto

class _Context:
    """Tudo o que uma chamada precisa, lido uma vez da mesma fonte da Visão Geral."""

    def __init__(self, db, filters: AnalyticsFilter, now: datetime):
        self.db = db
        self.filters = filters
        self.now = now
        self.analytics = IndustrialAnalyticsService(db, now_func=lambda: now)
        self.overview = self.analytics.management.get_overview(filters)
        self.operators = list(_call(db, "listar_operadores_apontamento", somente_ativos=False))
        self.rates = self._rates()
        self.resource_sector: dict[str, str] = {}
        self._unplanned = None
        self._physical = None
        self._stop_pieces = None
        self._assignments = None

    # Paradas não planejadas, exatamente as da análise de paradas.
    def unplanned_items(self):
        if self._unplanned is None:
            _available, states = self.analytics._resource_states(self.filters)
            by_id = {row.get("id"): row for row in states if row.get("id") is not None}
            items = []
            for item in self.analytics.downtimes(self.filters).get("items") or ():
                if item.get("automatica"):
                    continue
                row = by_id.get(item.get("estado_recurso_id")) or {
                    "categoria": EventCategory.DOWNTIME.value,
                    "motivo": item.get("motivo"),
                    "planejado": item.get("programada"),
                }
                classification = classify_state_row(row)
                if classification is None or not ManufacturingRules.stop_affects_oee(classification):
                    continue
                items.append(item)
            self._unplanned = items
        return self._unplanned

    # Trechos físicos JÁ consolidados com a regra da Visão Geral
    # (``consolidate_physical_time``): um estado por instante e recurso,
    # produção prevalece sobre parada, estados conflitantes viram desconhecido.
    def physical_segments(self):
        if self._physical is None:
            # Recurso pela identidade canônica antes de consolidar: o
            # agrupamento é o mesmo da Visão Geral, só o rótulo fica estável.
            inputs = [
                replace(item, resource=_resource_key(item.resource) or item.resource)
                for item in self.analytics.physical_inputs(self.filters)
            ]
            self._physical = consolidate_physical_time(inputs)["segments"]
        return self._physical

    def stop_pieces(self):
        """Trechos de parada não planejada com custo, já com um motivo cada.

        Só entra o instante que a Visão Geral classifica como parada não
        planejada (não "produção prevalece", não desconhecido) E que está
        coberto por uma parada não planejada da análise de paradas (fora as
        pausas automáticas). Paradas simultâneas com motivos diferentes no
        mesmo recurso não duplicam: o instante vai para a parada iniciada
        primeiro (empate: motivo em ordem alfabética).
        """
        if self._stop_pieces is not None:
            return self._stop_pieces
        windows = defaultdict(list)
        for segment in self.physical_segments():
            if (segment.category is EventCategory.DOWNTIME
                    and segment.stop_classification is not StopClassification.PLANNED):
                windows[_key(segment.resource)].append((segment.start, segment.end))
        items_by_resource = defaultdict(list)
        for item in self.unplanned_items():
            key = _resource_key(item.get("recurso"))
            if key and key != _UNKNOWN_RESOURCE and item["fim"] > item["inicio"]:
                items_by_resource[key].append(item)
        pieces = []
        for key in sorted(items_by_resource):
            allowed = _merge(windows.get(key, ()))
            if allowed:
                pieces.extend(_owned_stop_pieces(key, items_by_resource[key], allowed))
        self._stop_pieces = pieces
        return pieces

    def reasons(self, sector=None):
        seconds = defaultdict(float)
        for _resource, item_sector, start, end, label in self.stop_pieces():
            if sector is None or item_sector == sector:
                seconds[label] += (end - start).total_seconds()
        ranked = sorted(seconds.items(), key=lambda pair: (-pair[1], pair[0].casefold()))
        return [{"motivo": label, "horas": value / 3600.0} for label, value in ranked if value > 0]

    def stop_slices(self):
        windows = defaultdict(list)
        for key, sector, start, end, _label in self.stop_pieces():
            windows[key].append((start, end))
            self.resource_sector.setdefault(key, sector)
        return self._slices(windows)

    def work_slices(self):
        windows = defaultdict(list)
        for segment in self.physical_segments():
            key = _key(segment.resource)
            if segment.category not in _WORKED_CATEGORIES or not key or key == _UNKNOWN_RESOURCE:
                continue
            windows[key].append((segment.start, segment.end))
            self.resource_sector.setdefault(key, segment.sector)
        return self._slices(windows)

    def _slices(self, windows):
        slices = []
        assignments = self.assignments()
        for key in sorted(windows):
            people = assignments.get(key, ())
            for start, end in _merge(windows[key]):
                for sub_start, sub_end, crachas in _split_by_people(start, end, people):
                    slices.append(StopSlice(key, sub_start, sub_end, crachas))
        return slices

    # Cada instante de uma pessoa pertence a um único recurso: o da
    # participação iniciada mais recentemente (decisão do controlador 16/10).
    def assignments(self):
        if self._assignments is not None:
            return self._assignments
        cap = min(self.filters.fim, self.now)
        by_badge = defaultdict(list)
        for row in _call(self.db, "listar_participacoes_operador_periodo", self.filters.inicio, self.filters.fim):
            badge = _key(row.get("cracha_resolvido") or row.get("cracha"))
            resource = _resource_key(row.get("recurso"))
            began = _dt(row.get("data_inicio"))
            if not badge or not resource or began is None:
                continue
            start = max(began, self.filters.inicio)
            end = min(_dt(row.get("data_fim")) or cap, self.filters.fim)
            if end > start:
                by_badge[badge].append((began, resource, start, end))

        result = defaultdict(list)
        for badge, parts in by_badge.items():
            points = sorted({p for _b, _r, s, e in parts for p in (s, e)})
            owned = []
            for a, b in zip(points, points[1:]):
                covering = sorted(
                    ((began, res) for began, res, s, e in parts if s <= a and e >= b),
                    key=lambda item: item[1],
                )
                if not covering:
                    continue
                # Participação iniciada mais recentemente vence; empate: menor código.
                resource = max(covering, key=lambda item: item[0])[1]
                if owned and owned[-1][0] == resource and owned[-1][2] == a:
                    owned[-1] = (resource, owned[-1][1], b)
                else:
                    owned.append((resource, a, b))
            for resource, a, b in owned:
                result[resource].append((badge, a, b))
        self._assignments = dict(result)
        return self._assignments

    def people(self, slices):
        names = {_key(row.get("cracha")): row.get("nome") for row in self.operators}
        hours = defaultdict(Decimal)
        for stop in slices:
            duration = Decimal((stop.fim - stop.inicio) // timedelta(microseconds=1)) / Decimal(3_600_000_000)
            for badge in stop.pessoas:
                hours[badge] += duration
        people = []
        for badge, value in hours.items():
            rate = self.rates.pessoa.get(badge)
            people.append({
                "nome": names.get(badge) or badge,
                "horas": float(value.quantize(_CENTAVO, rounding=ROUND_HALF_UP)),
                "custo": _money(value * (rate or Decimal("0"))),
                "custo_completo": rate is not None,
            })
        people.sort(key=lambda item: (-item["horas"], str(item["nome"]).casefold()))
        return people

    def _rates(self):
        resource = {}
        for row in _call(self.db, "listar_custos_hora_recurso"):
            value = _decimal_or_none(row.get("valor_hora"))
            if value is not None:
                resource[_resource_key(row.get("recurso"))] = value
        badge_by_id = {row.get("id"): _key(row.get("cracha")) for row in self.operators}
        person = {}
        for row in _call(self.db, "listar_custos_hora_operador"):
            badge = badge_by_id.get(row.get("operador_id"))
            value = _decimal_or_none(row.get("valor_hora"))
            if badge and value is not None:
                person[badge] = value
        return CostRates(recurso=resource, pessoa=person)


# --------------------------------------------------------------------------- auxiliares

def _sheet_text(*, subject, worked_h, available_h, produced, stopped_h, stop_cost_value,
                main_reason, missing, feminine=False):
    pieces = "peça" if produced == 1 else "peças"
    text = (
        f"{subject} trabalhou {format_hours(worked_h)} de {format_hours(available_h)} "
        f"e produziu {produced} {pieces}."
    )
    if stopped_h > 0:
        stopped = "parada" if feminine else "parado"
        text += f" Ficou {stopped} {format_hours(stopped_h)}, o que custou {format_reais(stop_cost_value)}."
        if main_reason:
            text += f" Principal motivo: {main_reason['motivo']} ({format_hours(main_reason['horas'])})."
    else:
        text += " Sem paradas no período."
    if missing:
        text += f" Atenção: {_missing_warning(missing)}."
    return text


def _unplanned_stop_hours(hours) -> float:
    """Horas paradas na mesma conta da Visão Geral (``frontend_facade``):
    tempo de parada menos a parada planejada — o não classificado conta."""
    seconds = float(hours.get("downtime_seconds") or 0.0) - float(hours.get("planned_downtime_seconds") or 0.0)
    return max(0.0, seconds) / 3600.0


def _missing_keys(result: CostResult) -> set:
    return set(result.recursos_sem_custo) | set(result.pessoas_sem_custo)


def _missing_count(result: CostResult) -> int:
    return len(_missing_keys(result))


def _stop_label(item) -> str:
    return strip_status_code_prefix(item.get("motivo"), item.get("codigo_status")) or "Não informado"


def _owned_stop_pieces(resource, items, allowed):
    """Varre as paradas de um recurso e devolve trechos disjuntos com dono único.

    ``allowed`` (já unido e ordenado) são os instantes em que a Visão Geral diz
    que o recurso estava em parada não planejada. Dentro deles, cada instante
    pertence a uma única parada: a iniciada primeiro; empate pelo motivo.
    """
    ranked = sorted(
        items,
        key=lambda item: (item["inicio"], _stop_label(item).casefold(), str(item.get("estado_recurso_id"))),
    )
    points = sorted(
        {p for item in ranked for p in (item["inicio"], item["fim"])}
        | {p for window in allowed for p in window}
    )
    pieces = []
    window_index = 0
    next_item = 0
    active = []  # índices em ``ranked`` das paradas que cobrem o trecho
    for a, b in zip(points, points[1:]):
        while next_item < len(ranked) and ranked[next_item]["inicio"] <= a:
            active.append(next_item)
            next_item += 1
        active = [index for index in active if ranked[index]["fim"] > a]
        while window_index < len(allowed) and allowed[window_index][1] <= a:
            window_index += 1
        if not active or window_index >= len(allowed) or allowed[window_index][0] > a:
            continue
        owner = ranked[min(active)]
        label = _stop_label(owner)
        sector = owner.get("setor")
        if pieces and pieces[-1][4] == label and pieces[-1][3] == a and pieces[-1][1] == sector:
            pieces[-1] = (resource, sector, pieces[-1][2], b, label)
        else:
            pieces.append((resource, sector, a, b, label))
    return pieces


def _split_by_people(start, end, people):
    points = {start, end}
    for _badge, a, b in people:
        if start < a < end:
            points.add(a)
        if start < b < end:
            points.add(b)
    ordered = sorted(points)
    for a, b in zip(ordered, ordered[1:]):
        badges = tuple(sorted({badge for badge, s, e in people if s <= a and e >= b}))
        yield a, b, badges


def _merge(intervals):
    merged = []
    for start, end in sorted(intervals):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def _resource_catalog():
    """Recursos apontáveis (código canônico) com o setor de cada um."""
    catalog = []
    seen = set()
    for sector in OPERATOR_SECTORS:
        stations = sector.resources or (sector.name,)
        for station in stations:
            code = STATION_RESOURCE_CODES.get((sector.name.casefold(), str(station).casefold()), station)
            key = _resource_key(code)
            if key and key not in seen:
                seen.add(key)
                catalog.append((key, sector.name))
    return catalog


def _catalog_sector(key):
    for resource, sector in _resource_catalog():
        if resource == key:
            return sector
    return None


def _positive_rate(valor) -> Decimal:
    try:
        rate = Decimal(str(valor).strip())
        if rate.is_finite():
            rate = rate.quantize(_CENTAVO, rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError, TypeError):
        rate = None
    if rate is None or not rate.is_finite() or rate <= 0 or rate >= _MAX_RATE:
        raise DirectorSummaryError(
            "COST_RATE_INVALID",
            "O valor por hora precisa ser maior que zero (até 2 casas) e menor que 10 bilhões.",
            status_code=422,
            details={"valor_hora": str(valor)},
        )
    return rate


def _call(db, name, *args, **kwargs):
    loader = getattr(db, name, None)
    if not callable(loader):
        return []
    return list(loader(*args, **kwargs) or [])


def _key(value) -> str:
    return str(value or "").strip().upper()


def _resource_key(value) -> str:
    text = str(value or "").strip()
    return _key(resolve_resource_identity(text) if text else text)


def _decimal_or_none(value):
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _float_or_none(value):
    return None if value is None else float(value)


def _money(value) -> float:
    return float(Decimal(value).quantize(_CENTAVO, rounding=ROUND_HALF_UP))


def _dt(value):
    if value is None or isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
