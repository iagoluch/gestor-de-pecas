"""Explicação dos números da aba Diretoria (``dir.*``, 20/10/2026).

Cada número do Painel, da Ficha e dos Custos abre uma conta com valores reais.
Nada é recalculado por fora: o serviço reaproveita o mesmo ``_Context`` do
resumo (mesma fonte, mesmo filtro de período) e só desmonta o resultado em
partes que somam o número clicado. Quando o cadastro de custo está incompleto,
a conta mostra quem ficou sem valor da hora e o total é dito incompleto.

Valores em reais só saem por aqui, atrás da porta da Diretoria
(``/diretoria/explicacao``): quem não é da Diretoria nunca recebe estes números.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal

from app.core.resource_mapping import resource_display_name
from mes.contracts import AnalyticsFilter
from mes.domain.director_cost import CostResult, stop_cost, work_cost
from mes.services.director_summary import (
    DirectorSummaryError,
    _Context,
    _call,
    _key,
    _missing_keys,
    _missing_warning,
    _money,
    _resource_key,
    _unplanned_stop_hours,
    format_hours,
    format_reais,
    resolve_period,
)
from mes.services.kpi_explanation import KpiExplanationService
from mes.services.value_explanation import (
    ValueExplanation,
    ValueExplanationService,
    ValueNode,
    _iso,
    _reconciliation,
)

METRICS = (
    "dir.produzido",
    "dir.horas_paradas",
    "dir.custo_parada",
    "dir.eficiencia",
    "dir.trabalhou",
    "dir.parado_motivo",
    "dir.custo_trabalho",
    "dir.custo_setor",
    "dir.valor_hora",
)

_MICROS_PER_HOUR = Decimal(3_600_000_000)
_SECTOR_MISSING = "Sem setor identificado"


class DirectorExplanationService:
    def __init__(self, db):
        self.db = db

    def explain(
        self,
        metric,
        period,
        *,
        setor=None,
        recurso=None,
        pessoa=None,
        motivo=None,
        now: datetime,
    ) -> ValueExplanation:
        metric = str(metric or "").strip()
        if metric not in METRICS:
            raise DirectorSummaryError(
                "UNKNOWN_METRIC",
                f"Número desconhecido na Diretoria: {metric or '(vazio)'}.",
                status_code=422,
                details={"metric": metric, "aceitos": list(METRICS)},
            )
        start, end = resolve_period(period, now)
        setor = _text(setor)
        recurso = _text(recurso)
        if metric == "dir.custo_setor":
            if not setor:
                raise DirectorSummaryError(
                    "SECTOR_REQUIRED", "Informe o setor para abrir o custo do setor.", status_code=422
                )
            # O Painel calcula o custo por setor sobre o período inteiro.
            filters = AnalyticsFilter(start, end)
        elif metric == "dir.valor_hora":
            filters = AnalyticsFilter(start, end)
        else:
            filters = AnalyticsFilter(start, end, setor=setor or None, recurso=recurso or None)
        ctx = _Context(self.db, filters, now)
        if metric == "dir.produzido":
            return self._produzido(ctx)
        if metric == "dir.eficiencia":
            return self._eficiencia(ctx)
        if metric == "dir.horas_paradas":
            return self._horas_paradas(ctx)
        if metric == "dir.trabalhou":
            return self._trabalhou(ctx)
        if metric == "dir.parado_motivo":
            return self._parado_motivo(ctx, _text(motivo))
        if metric == "dir.custo_parada":
            return self._custo(ctx, metric, "Custo das paradas", ctx.stop_slices(), stop_cost, "parou", setor_filter=setor)
        if metric == "dir.custo_trabalho":
            return self._custo(ctx, metric, "Custo do trabalho", ctx.work_slices(), work_cost, "trabalhou", setor_filter=setor)
        if metric == "dir.custo_setor":
            return self._custo_setor(ctx, setor)
        return self._valor_hora(ctx, recurso=recurso, pessoa=_text(pessoa))

    # ------------------------------------------------------------------ D1 e D4

    def _produzido(self, ctx: _Context) -> ValueExplanation:
        inner = ValueExplanationService(ctx.analytics.management, self.db).explain("qtd.boa", ctx.filters)
        return replace(inner, metric="dir.produzido", label="Produzido", notes=[*inner.notes, _period_note(ctx)])

    def _eficiencia(self, ctx: _Context) -> ValueExplanation:
        service = KpiExplanationService(ctx.analytics.management, now_func=lambda: ctx.now)
        inner = service.explain("kpi.oee", ctx.filters)
        return replace(inner, metric="dir.eficiencia", label="Eficiência (OEE)", notes=[*inner.notes, _period_note(ctx)])

    # --------------------------------------------------------------- D2 (horas)

    def _horas_paradas(self, ctx: _Context) -> ValueExplanation:
        hours = ctx.overview.get("hours") or {}
        value = _unplanned_stop_hours(hours)
        planned_by_sector = {
            item.get("setor"): float(item.get("parada_planejada_segundos") or 0.0)
            for item in ctx.overview.get("sector_kpis") or ()
        }
        children = []
        for sector in ctx.overview.get("sectors") or ():
            name = sector.get("setor")
            total = float(sector.get("tempo_parado_segundos") if sector.get("tempo_parado_segundos") is not None
                          else sector.get("tempo_parada_segundos") or 0.0)
            planned = planned_by_sector.get(name, 0.0)
            seconds = total - planned
            if seconds <= 0:
                continue
            children.append(ValueNode(
                "sector", str(name or _SECTOR_MISSING), seconds / 3600.0, [],
                {"Tempo parado": format_hours(total / 3600.0), "Parada planejada (fora)": format_hours(planned / 3600.0)},
            ))
        children.sort(key=lambda node: (-(node.value or 0.0), node.label.casefold()))
        listed = sum(node.value or 0.0 for node in children)
        remainder = value - listed
        if remainder > 1e-6:
            children.append(ValueNode(
                "group", "Parada sem setor identificado", remainder, [],
                {"Motivo": "Entra no total da Visão Geral, mas o tempo não está ligado a um setor."},
            ))
        excluded = []
        for label, key, why in (
            ("Parada planejada", "planned_downtime_seconds", "combinada de antemão: não conta como parada."),
            ("Sem demanda", "no_demand_seconds", "máquina livre por falta de OP: não é parada."),
            ("Fora do turno", "out_of_shift_seconds", "fora do horário de trabalho: não é parada."),
        ):
            seconds = float(hours.get(key) or 0.0)
            if seconds > 0:
                excluded.append({"label": label, "value": seconds, "unidade": "segundos", "reason": why})
        return _build(
            ctx, "dir.horas_paradas", "Horas paradas", "hours", value,
            reason=(
                f"{format_hours(value)} de parada não planejada no período, somando os setores abaixo."
                if value > 0 else "Nenhuma parada não planejada no período."
            ),
            rule="Horas paradas = tempo de parada − paradas planejadas. Sem demanda e fora do turno nunca entram.",
            children=children, excluded=excluded,
        )

    # -------------------------------------------------------------- D5 (trabalho)

    def _trabalhou(self, ctx: _Context) -> ValueExplanation:
        bases = ctx.overview.get("kpi_time_bases") or {}
        worked = float(bases.get("worked_seconds") or 0.0) / 3600.0
        available = float(bases.get("available_seconds") or 0.0) / 3600.0
        per_resource = _micros_by_resource(ctx.work_slices())
        children = [
            ValueNode("resource", _resource_name(key), float(Decimal(micros) / _MICROS_PER_HOUR), [], None)
            for key, micros in per_resource.items()
        ]
        children.sort(key=lambda node: (-(node.value or 0.0), node.label.casefold()))
        remainder = worked - sum(node.value or 0.0 for node in children)
        if remainder > 1e-6:
            children.append(ValueNode(
                "group", "Trabalho sem recurso identificado", remainder, [],
                {"Motivo": "Entra no total da Visão Geral, mas não está ligado a um recurso."},
            ))
        notes = []
        if available > 0:
            notes.append(
                f"Disponível no período: {format_hours(available)}. "
                f"Trabalhou {worked / available * 100:.0f}% do tempo disponível."
            )
        return _build(
            ctx, "dir.trabalhou", "Trabalhou", "hours", worked,
            reason=f"Os recursos trabalharam {format_hours(worked)} no período.",
            rule="Trabalhou = tempo em atividade produtiva registrada, a mesma base da Eficiência (OEE).",
            children=children, notes=notes,
        )

    # ------------------------------------------------------------- D6 (motivos)

    def _parado_motivo(self, ctx: _Context, motivo: str = "") -> ValueExplanation:
        by_reason: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
        for resource, _sector, start, end, label in ctx.stop_pieces():
            by_reason[label][resource] += (end - start).total_seconds()
        children = []
        for label, resources in by_reason.items():
            seconds = sum(resources.values())
            if seconds <= 0:
                continue
            inner = [ValueNode("resource", _resource_name(key), value / 3600.0, [], None)
                     for key, value in resources.items() if value > 0]
            inner.sort(key=lambda node: (-(node.value or 0.0), node.label.casefold()))
            children.append(ValueNode("group", label, seconds / 3600.0, inner, None))
        children.sort(key=lambda node: (-(node.value or 0.0), node.label.casefold()))
        if motivo:
            children = [node for node in children if node.label.casefold() == motivo.casefold()]
            value = sum(node.value or 0.0 for node in children)
            label = children[0].label if children else motivo
            return _build(
                ctx, "dir.parado_motivo", f"Parado por {label}", "hours", value,
                reason=(
                    f"{format_hours(value)} parados por {label}, separados pelo recurso."
                    if value > 0 else f"Sem paradas não planejadas por {label} no período."
                ),
                rule="Cada instante de parada vai para um único motivo: o da parada iniciada primeiro naquele recurso.",
                children=[child for node in children for child in node.children],
            )
        value = sum(item["horas"] for item in ctx.reasons())
        notes = []
        card = _unplanned_stop_hours(ctx.overview.get("hours") or {})
        if abs(card - value) > 0.005:
            notes.append(
                f"O número Parado mostra {format_hours(card)}; a diferença de {format_hours(abs(card - value))} "
                "é parada que não aparece em nenhum motivo (sem recurso identificado ou já contada em outra parada ao mesmo tempo)."
            )
        return _build(
            ctx, "dir.parado_motivo", "Parado por motivo", "hours", value,
            reason=(
                f"{format_hours(value)} parados, separados pelo motivo que o operador registrou."
                if value > 0 else "Sem paradas não planejadas no período."
            ),
            rule="Cada instante de parada vai para um único motivo: o da parada iniciada primeiro naquele recurso.",
            children=children, notes=notes,
        )

    # ----------------------------------------------------------------- Custos

    def _custo(self, ctx, metric, label, slices, cost_fn, verb, *, setor_filter="") -> ValueExplanation:
        official = cost_fn(slices, ctx.rates)
        with_sectors = not setor_filter and not ctx.filters.recurso
        return self._cost_explanation(ctx, metric, label, slices, official, verb=verb, with_sectors=with_sectors)

    def _custo_setor(self, ctx: _Context, setor: str) -> ValueExplanation:
        # ``stop_slices`` primeiro: é ele que liga cada recurso ao seu setor.
        slices = [item for item in ctx.stop_slices() if _same_text(ctx.resource_sector.get(item.recurso), setor)]
        official = stop_cost(slices, ctx.rates)
        return self._cost_explanation(
            ctx, "dir.custo_setor", f"Custo das paradas · {setor}", slices, official, verb="parou", with_sectors=False
        )

    def _cost_explanation(self, ctx, metric, label, slices, official: CostResult, *, verb, with_sectors) -> ValueExplanation:
        machine: dict[str, int] = defaultdict(int)
        people: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        for item in slices:
            micros = max(0, (item.fim - item.inicio) // timedelta(microseconds=1))
            machine[item.recurso] += micros
            for badge in {_key(p) for p in item.pessoas} - {""}:
                people[item.recurso][badge] += micros
        names = {_key(row.get("cracha")): row.get("nome") for row in ctx.operators}
        resource_nodes: dict[str, ValueNode] = {}
        leaf_count = 0
        for key in sorted(machine):
            leaves = [_leaf("Máquina", machine[key], ctx.rates.recurso.get(key))]
            ranked = sorted(people[key], key=lambda badge: (-people[key][badge], badge))
            leaves.extend(_leaf(names.get(badge) or badge, people[key][badge], ctx.rates.pessoa.get(badge)) for badge in ranked)
            leaf_count += len(leaves)
            detail = {"Tempo": format_hours(float(Decimal(machine[key]) / _MICROS_PER_HOUR))}
            sector = ctx.resource_sector.get(key)
            if sector:
                detail = {"Setor": sector, **detail}
            resource_nodes[key] = ValueNode(
                "resource", _resource_name(key), _cents(sum(leaf.value or 0.0 for leaf in leaves)), leaves, detail
            )
        if with_sectors:
            by_sector: dict[str, list[ValueNode]] = defaultdict(list)
            for key, node in resource_nodes.items():
                by_sector[ctx.resource_sector.get(key) or _SECTOR_MISSING].append(node)
            top = []
            for sector, nodes in by_sector.items():
                nodes.sort(key=lambda node: (-(node.value or 0.0), node.label.casefold()))
                top.append(ValueNode("sector", sector, _cents(sum(node.value or 0.0 for node in nodes)), nodes, None))
        else:
            top = list(resource_nodes.values())
        top.sort(key=lambda node: (-(node.value or 0.0), node.label.casefold()))

        value = _money(official.custo)
        diff = _cents(value - sum(node.value or 0.0 for node in top))
        # Cada folha é arredondada ao centavo; o total só é arredondado no fim.
        # Uma sobra de centavos é arredondamento; diferença maior é problema real
        # e fica visível no alerta de conferência.
        if diff != 0.0 and abs(diff) <= 0.005 * leaf_count + 0.01:
            top.append(ValueNode("input", "Arredondamento (centavos)", diff, [], None))

        notes = []
        missing = _missing_keys(official)
        if missing:
            who = sorted(
                [_resource_name(key) for key in official.recursos_sem_custo]
                + [str(names.get(key) or key) for key in official.pessoas_sem_custo],
                key=str.casefold,
            )
            notes.append(
                f"Atenção: {_missing_warning(len(missing))}. Sem valor da hora cadastrado: {', '.join(who)}. "
                "Cadastre na tela de Custos da Diretoria."
            )
        elif not top:
            notes.append("Sem horas no período, o custo é zero.")
        return _build(
            ctx, metric, label, "brl", value,
            reason=(
                f"{format_reais(value)} no período: o tempo que cada recurso {verb}, multiplicado pelo valor da hora da máquina "
                "e de quem estava nela."
                if value > 0 else f"Nenhum custo no período: sem horas {'paradas' if verb == 'parou' else 'trabalhadas'} com valor da hora cadastrado."
            ),
            rule=(
                "Custo = horas de cada recurso × (valor da hora da máquina + valor da hora de cada pessoa presente). "
                "Sem valor cadastrado, a parte conta como zero e o total fica incompleto."
            ),
            children=top, notes=notes, money=True,
        )

    # --------------------------------------------------------------- D9 (valor)

    def _valor_hora(self, ctx: _Context, *, recurso: str, pessoa: str) -> ValueExplanation:
        if not recurso and not pessoa:
            raise DirectorSummaryError(
                "RATE_TARGET_REQUIRED", "Informe o recurso ou a pessoa para abrir o valor da hora.", status_code=422
            )
        stop_slices = ctx.stop_slices()
        work_slices = ctx.work_slices()
        if recurso:
            key = _resource_key(recurso)
            rate = ctx.rates.recurso.get(key)
            row = next(
                (item for item in _call(self.db, "listar_custos_hora_recurso") if _resource_key(item.get("recurso")) == key),
                None,
            )
            subject = _resource_name(key)
            stop_micros = sum(_micros(s) for s in stop_slices if s.recurso == key)
            work_micros = sum(_micros(s) for s in work_slices if s.recurso == key)
            what = f"da máquina {subject}"
        else:
            operator = next((op for op in ctx.operators if str(op.get("id")) == pessoa), None)
            if operator is None:
                raise DirectorSummaryError(
                    "UNKNOWN_PERSON", "Pessoa não encontrada.", status_code=404, details={"operador_id": pessoa}
                )
            badge = _key(operator.get("cracha"))
            rate = ctx.rates.pessoa.get(badge)
            row = next(
                (item for item in _call(self.db, "listar_custos_hora_operador") if str(item.get("operador_id")) == pessoa),
                None,
            )
            subject = str(operator.get("nome") or badge)
            stop_micros = sum(_micros(s) for s in stop_slices if badge in {_key(p) for p in s.pessoas})
            work_micros = sum(_micros(s) for s in work_slices if badge in {_key(p) for p in s.pessoas})
            what = f"de {subject}"

        children = []
        for text, micros in (("Tempo parado no período", stop_micros), ("Tempo trabalhado no período", work_micros)):
            hours = Decimal(micros) / _MICROS_PER_HOUR
            used = f"{format_reais(float(hours * rate))} de custo" if rate is not None else "sem valor cadastrado"
            children.append(ValueNode(
                "input", f"{text} ({used})", micros / 1_000_000.0, [], {"unidade": "segundos"}
            ))
        notes = ["O sistema guarda só o valor atual: não há histórico de valores anteriores, então períodos passados usam o valor de hoje."]
        if row is not None and (row.get("atualizado_em") or row.get("atualizado_por")):
            stamp = row.get("atualizado_em")
            when = stamp.strftime("%d/%m/%Y %H:%M") if hasattr(stamp, "strftime") else _text(stamp)
            who = _text(row.get("atualizado_por"))
            notes.insert(0, "Última alteração: " + " ".join(part for part in (when, f"por {who}" if who else "") if part) + ".")
        value = float(rate) if rate is not None else None
        return ValueExplanation(
            metric="dir.valor_hora",
            label=f"Valor da hora {what}",
            unit="brl",
            value=value,
            reason=(
                f"{format_reais(value)} por hora, cadastrado pela Diretoria."
                if value is not None else "Nenhum valor da hora cadastrado: o custo desta parte conta como zero."
            ),
            rule="O valor da hora é digitado pela Diretoria e multiplicado pelo tempo parado e trabalhado nas contas de custo.",
            children=children,
            excluded=[],
            reconciliation={"ok": True, "sum": None, "diff": None},
            calculated_at=_iso(ctx.now),
            truncated=False,
            notes=[_period_note(ctx), *notes],
        )


# ------------------------------------------------------------------ auxiliares

def _build(ctx, metric, label, unit, value, *, reason, rule, children, excluded=None, notes=None, money=False):
    total = sum(node.value or 0.0 for node in children)
    return ValueExplanation(
        metric=metric,
        label=label,
        unit=unit,
        value=value,
        reason=reason,
        rule=rule,
        children=children,
        excluded=excluded or [],
        reconciliation=_reconciliation(value, round(total, 2) if money else total),
        calculated_at=_iso(ctx.now),
        truncated=False,
        notes=[_period_note(ctx), *(notes or [])],
    )


def _period_note(ctx: _Context) -> str:
    start, end = ctx.filters.inicio, ctx.filters.fim
    scope = ""
    if ctx.filters.setor:
        scope += f" Setor: {ctx.filters.setor}."
    if ctx.filters.recurso:
        scope += f" Recurso: {_resource_name(_resource_key(ctx.filters.recurso))}."
    return f"Período: {start:%d/%m/%Y %H:%M} a {end:%d/%m/%Y %H:%M}.{scope}"


def _leaf(label: str, micros: int, rate) -> ValueNode:
    hours = Decimal(micros) / _MICROS_PER_HOUR
    shown = format_hours(float(hours))
    if rate is None:
        return ValueNode("input", f"{label} · {shown} × valor da hora não cadastrado", 0.0, [], None)
    return ValueNode("input", f"{label} · {shown} × {format_reais(float(rate))}/h", _money(hours * rate), [], None)


def _micros(item) -> int:
    return max(0, (item.fim - item.inicio) // timedelta(microseconds=1))


def _micros_by_resource(slices) -> dict[str, int]:
    totals: dict[str, int] = defaultdict(int)
    for item in slices:
        totals[item.recurso] += _micros(item)
    return dict(totals)


def _resource_name(key: str) -> str:
    return resource_display_name(key) or key


def _cents(value: float) -> float:
    return round(float(value), 2)


def _same_text(left, right) -> bool:
    return _text(left).casefold() == _text(right).casefold()


def _text(value) -> str:
    return str(value or "").strip()
