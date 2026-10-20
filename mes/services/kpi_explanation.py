"""Explicação de valor da família ``kpi.*``: OEE e seus componentes de tempo.

Contrato: ``docs/superpowers/specs/2026-10-19-explicacao-valor-contrato.md``.

Sem conta própria, como em ``value_explanation``: o número é o de
``ManagementService.get_overview`` (``kpis`` e ``kpis_estendidos``), o mesmo da
Visão Geral e de Análises > OEE. A árvore mostra a fórmula com as bases de
tempo que o calculador canônico (``mes/analytics/oee.py``) devolveu
(``kpi_time_bases``) e, por setor e recurso, o valor e as bases de cada um
(``sector_kpis`` e ``resource_kpis``).

A ``reconciliation`` refaz a conta somando as bases dos recursos (taxas) ou
multiplicando os componentes (OEE) e compara com o número da tela. Recurso que
não entra na soma (período todo sem demanda) vai para ``excluded`` e ``notes``;
diferença de bases aparece como diferença, nunca é corrigida em silêncio.

O FTT continua explicado por ``qtd.ftt``; aqui ele só aparece como componente
do OEE.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from mes.analytics.oee import (
    OEE_RULE_VERSION,
    PERFORMANCE_ABOVE_LIMIT_ALERT,
    RESULT_ORIGIN_NO_DEMAND,
)
from mes.contracts import AnalyticsFilter
from mes.services.metric_explanation import UnknownMetricError
from mes.services.value_explanation import (
    MAX_LEAVES_PER_RESOURCE,
    ValueExplanation,
    ValueNode,
    _any_truncated,
)


_TOLERANCE = 1e-6
_NO_SECTOR = "Não informado"
_NO_RESOURCE = "Sem recurso informado"

# Bases de tempo de ``calculate_oee`` (``kpi_time_bases``), em português simples.
_BASE_LABEL = {
    "worked_seconds": "Tempo trabalhado",
    "available_seconds": "Tempo disponível",
    "operational_seconds": "Tempo operacional",
    "productive_net_seconds": "Tempo produtivo líquido",
    "productive_gross_seconds": "Tempo em produção",
}
_BASE_CONTENT = {
    "worked_seconds": "Produção + Setup + Retrabalho + Atividade sem OP.",
    "available_seconds": (
        "Tempo trabalhado + Parada não planejada + Sem identificação (recurso "
        "sem estado conhecido)."
    ),
    "operational_seconds": (
        "Hoje é o mesmo tempo disponível: tempo trabalhado + Parada não "
        "planejada + Sem identificação."
    ),
    "productive_net_seconds": (
        "Tempo padrão das peças boas + tempo de apoio (Setup + Retrabalho + "
        "Atividade sem OP). Peça boa sem tempo padrão não soma."
    ),
    "productive_gross_seconds": "Só o tempo em Produção.",
}
_OUTSIDE_AVAILABLE = "Parada planejada, Sem demanda, Fila e Fora de turno."

# Chave do detalhe de um recurso/setor para cada base (o painel vira "Tempo trabalhado").
_BASE_DETAIL_KEY = {
    "worked_seconds": "tempo_trabalhado",
    "available_seconds": "tempo_disponível",
    "operational_seconds": "tempo_operacional",
    "productive_net_seconds": "tempo_produtivo_líquido",
    "productive_gross_seconds": "tempo_em_produção",
}

_COMPONENTS = (
    ("availability", "Disponibilidade", "kpi.disponibilidade"),
    ("performance", "Performance", "kpi.performance"),
    ("ftt", "FTT", "qtd.ftt"),
)

KPI_TEXT: dict[str, dict[str, Any]] = {
    "kpi.oee": {
        "label": "OEE",
        "section": "kpis",
        "key": "oee",
        "metric_key": "oee",
        "rule": (
            "OEE = Disponibilidade × Performance × FTT. Cada parte é calculada "
            "com as horas e as peças somadas de todos os recursos do filtro, "
            "nunca pela média dos percentuais."
        ),
    },
    "kpi.disponibilidade": {
        "label": "Disponibilidade",
        "section": "kpis",
        "key": "availability",
        "metric_key": "availability",
        "numerator": "worked_seconds",
        "denominator": "available_seconds",
        "rule": (
            "Disponibilidade = tempo trabalhado ÷ tempo disponível × 100. "
            "Trabalhado = Produção + Setup + Retrabalho + Atividade sem OP. "
            "Disponível = trabalhado + Parada não planejada + Sem identificação. "
            "Parada planejada, Sem demanda, Fila e Fora de turno ficam de fora."
        ),
        "reason": "O recurso trabalhou {num} dos {den} em que podia trabalhar.",
    },
    "kpi.performance": {
        "label": "Performance",
        "section": "kpis",
        "key": "performance",
        "metric_key": "performance",
        "numerator": "productive_net_seconds",
        "denominator": "worked_seconds",
        "rule": (
            "Performance = (tempo padrão das peças boas + tempo de apoio) ÷ "
            "tempo trabalhado × 100. Apoio = Setup + Retrabalho + Atividade sem "
            "OP. Peça boa sem tempo padrão cadastrado não soma no numerador."
        ),
        "reason": (
            "As peças boas e o apoio valem {num} pelo tempo padrão, em {den} "
            "de tempo trabalhado."
        ),
    },
    "kpi.ae": {
        "label": "AE (eficiência do ativo)",
        "section": "kpis_estendidos",
        "key": "ae",
        "metric_key": None,
        "numerator": "productive_net_seconds",
        "denominator": "available_seconds",
        "rule": (
            "AE = (tempo padrão das peças boas + tempo de apoio) ÷ tempo "
            "disponível × 100. Usa o mesmo numerador da Performance e o mesmo "
            "denominador da Disponibilidade."
        ),
        "reason": (
            "As peças boas e o apoio valem {num} pelo tempo padrão, em {den} "
            "de tempo disponível."
        ),
    },
    "kpi.produtividade": {
        "label": "Produtividade",
        "section": "kpis_estendidos",
        "key": "productivity",
        "metric_key": None,
        "numerator": "productive_gross_seconds",
        "denominator": "operational_seconds",
        "rule": (
            "Produtividade = tempo em Produção ÷ tempo operacional × 100. O "
            "tempo operacional é o mesmo tempo disponível; Setup, Retrabalho e "
            "Atividade sem OP não contam no numerador."
        ),
        "reason": "O recurso esteve produzindo {num} dos {den} de tempo operacional.",
    },
    "kpi.utilizacao": {
        "label": "Utilização",
        "section": "kpis_estendidos",
        "key": "utilization",
        "metric_key": None,
        "numerator": "worked_seconds",
        "denominator": "operational_seconds",
        "rule": (
            "Utilização = tempo trabalhado ÷ tempo operacional × 100. O tempo "
            "operacional é o mesmo tempo disponível."
        ),
        "reason": "O recurso trabalhou {num} dos {den} de tempo operacional.",
    },
}

_NOTE_UTILIZATION_EQUALS_AVAILABILITY = (
    "Hoje o tempo operacional é igual ao tempo disponível, então a Utilização "
    "usa as mesmas bases da Disponibilidade e dá o mesmo número (exceto no "
    "período todo sem demanda)."
)
_NOTE_RESOURCE_RATIO = (
    "A tela mostra este indicador só no total. O valor de cada setor e recurso "
    "aqui é a mesma conta aplicada às horas dele."
)
_NOTE_FTT = (
    "O FTT é o mesmo do cartão FTT; clique nele para ver as peças boas, o "
    "refugo e o retrabalho que entram na conta."
)


def _hms(seconds: float | None) -> str:
    total = max(0, int(round(float(seconds or 0.0))))
    hours, rest = divmod(total, 3600)
    minutes = rest // 60
    if hours:
        return f"{hours}h {minutes:02d}min"
    if minutes:
        return f"{minutes}min"
    return f"{total}s" if total else "0min"


def _time_text(seconds: float | None) -> str:
    """Duração legível com os segundos exatos, para a conta poder ser refeita."""

    value = float(seconds or 0.0)
    exact = int(value) if value == int(value) else round(value, 3)
    return f"{_hms(value)} ({exact} s)"


def _pct(value: float | None) -> str:
    if value is None:
        return "indisponível"
    return f"{value:.1f}".replace(".", ",") + "%"


def _base(bases: dict, key: str) -> float:
    return max(0.0, float((bases or {}).get(key) or 0.0))


def _ratio(numerator: float, denominator: float) -> float | None:
    return numerator / denominator * 100.0 if denominator > 0 else None


def _is_no_demand(calculation: dict | None) -> bool:
    return (calculation or {}).get("result_origin") == RESULT_ORIGIN_NO_DEMAND


class KpiExplanationService:
    def __init__(self, management, now_func=None):
        self.management = management
        self._clock = now_func

    def explain(
        self,
        metric: str,
        filters: AnalyticsFilter,
        *,
        max_leaves: int = MAX_LEAVES_PER_RESOURCE,
    ) -> ValueExplanation:
        text = KPI_TEXT.get(metric)
        if text is None:
            raise UnknownMetricError(f"Métrica desconhecida: {metric!r}")

        overview = self.management.get_overview(filters)
        shown = dict((overview.get(text["section"]) or {}).get(text["key"]) or {})
        raw = shown.get("value")
        value = float(raw) if raw is not None else None
        calculation = overview.get("kpi_calculation") or {}
        resources = list(overview.get("resource_kpis") or [])
        sectors = list(overview.get("sector_kpis") or [])
        total_exception = _is_no_demand(calculation)
        exception_resources = [row for row in resources if _is_no_demand(row.get("kpi_calculation"))]

        notes: list[str] = []
        excluded: list[dict] = []
        if metric == "kpi.oee":
            children, reason, reconciliation = self._explain_oee(
                overview, value, shown, resources, sectors, max_leaves
            )
        else:
            children, reason, reconciliation = self._explain_ratio(
                text, overview, value, shown, resources, sectors,
                total_exception, notes, excluded, max_leaves,
            )

        self._common_notes(
            metric, text, overview, shown, value, calculation, resources, sectors,
            total_exception, exception_resources, notes,
        )
        if exception_resources and not total_exception:
            for row in exception_resources:
                excluded.append({
                    "label": f"{row.get('resource') or _NO_RESOURCE} (período todo sem demanda)",
                    "value": _base(row.get("kpi_time_bases"), "no_demand_seconds"),
                    "unidade": "segundos",
                    "reason": (
                        "Recurso sem nenhuma OP no período: mostra o resultado da "
                        "regra sem demanda, mas o tempo dele não entra no total."
                    ),
                })

        return ValueExplanation(
            metric=metric,
            label=text["label"],
            unit="pct",
            value=value,
            reason=reason,
            rule=text["rule"],
            children=children,
            excluded=excluded,
            reconciliation=reconciliation,
            calculated_at=self._now().isoformat(),
            truncated=_any_truncated(children),
            notes=notes,
        )

    def _now(self) -> datetime:
        for clock in (self._clock, getattr(self.management, "_now", None)):
            if callable(clock):
                moment = clock()
                if isinstance(moment, datetime):
                    return moment
        return datetime.now()

    # ------------------------------------------------------------------ taxas

    def _explain_ratio(
        self, text, overview, value, shown, resources, sectors,
        total_exception, notes, excluded, max_leaves,
    ):
        bases = overview.get("kpi_time_bases") or {}
        hours = overview.get("hours") or {}
        num_key, den_key = text["numerator"], text["denominator"]
        numerator, denominator = _base(bases, num_key), _base(bases, den_key)

        if value is None:
            reason = shown.get("reason") or "Não há dados no filtro para calcular este indicador."
            reconciliation = {"ok": True, "sum": None, "diff": None, "method": "indisponivel"}
            return [], reason, reconciliation

        children = [
            self._base_input(
                f"Numerador: {_BASE_LABEL[num_key]}", num_key, bases, hours, notes, total_exception
            ),
            self._base_input(
                f"Denominador: {_BASE_LABEL[den_key]}", den_key, bases, hours, notes, total_exception
            ),
        ]
        children.extend(self._sector_nodes(text, sectors, resources, max_leaves))
        reason = text["reason"].format(num=_hms(numerator), den=_hms(denominator))

        if den_key in ("available_seconds", "operational_seconds"):
            # Recurso que ficou o período todo sem demanda já aparece sozinho em `explain`;
            # aqui sai do "Recurso sem demanda" geral para o mesmo tempo não contar duas vezes.
            listed = 0.0 if total_exception else sum(
                _base(row.get("kpi_time_bases"), "no_demand_seconds")
                for row in resources if _is_no_demand(row.get("kpi_calculation"))
            )
            excluded.extend(self._outside_available(hours, total_exception, listed))

        if total_exception:
            if text["metric_key"] is not None and shown.get("reason"):
                reason = str(shown["reason"])
            reconciliation = self._exception_reconciliation(text, value, numerator, denominator)
            return children, reason, reconciliation

        counted = [row for row in resources if not _is_no_demand(row.get("kpi_calculation"))]
        sum_num = sum(_base(row.get("kpi_time_bases"), num_key) for row in counted)
        sum_den = sum(_base(row.get("kpi_time_bases"), den_key) for row in counted)
        recomposed = _ratio(sum_num, sum_den)
        reconciliation = {
            "ok": recomposed is not None and abs(recomposed - value) <= _TOLERANCE,
            "sum": recomposed,
            "diff": (recomposed - value) if recomposed is not None else None,
            "method": "soma_das_bases_dos_recursos",
        }
        for key, total, summed in ((num_key, numerator, sum_num), (den_key, denominator, sum_den)):
            if abs(total - summed) > _TOLERANCE:
                notes.append(
                    f"A soma do {_BASE_LABEL[key].lower()} dos recursos ({_hms(summed)}) "
                    f"não fecha com o total ({_hms(total)}). Diferença de "
                    f"{_hms(abs(total - summed))}: pode ser tempo de registro sem "
                    "recurso informado. O número da tela usa o total."
                )
        return children, reason, reconciliation

    def _exception_reconciliation(self, text, value, numerator, denominator):
        if text["metric_key"] is not None:
            # 100% / 0% / 0% por regra corporativa, não pela conta das bases.
            return {"ok": True, "sum": value, "diff": 0.0, "method": "regra_sem_demanda"}
        recomposed = _ratio(numerator, denominator)
        return {
            "ok": recomposed is not None and abs(recomposed - value) <= _TOLERANCE,
            "sum": recomposed,
            "diff": (recomposed - value) if recomposed is not None else None,
            "method": "bases_do_total",
        }

    def _base_input(self, label, key, bases, hours, notes, total_exception=False) -> ValueNode:
        seconds = _base(bases, key)
        parts = self._base_parts(key, bases, hours, total_exception)
        children = [
            ValueNode(
                kind="input",
                label=part_label,
                value=part_seconds,
                detail={
                    "unidade": "segundos",
                    "tempo": _time_text(part_seconds),
                    **({"metric": metric} if metric else {}),
                },
            )
            for part_label, part_seconds, metric in parts
        ]
        if parts:
            parts_sum = sum(part[1] for part in parts)
            if abs(parts_sum - seconds) > _TOLERANCE:
                notes.append(
                    f"As partes do {_BASE_LABEL[key].lower()} somam {_hms(parts_sum)} "
                    f"e a base do cálculo é {_hms(seconds)}."
                )
        detail = {
            "unidade": "segundos",
            "tempo": _time_text(seconds),
            "o_que_entra": _BASE_CONTENT[key],
        }
        if key in ("available_seconds", "operational_seconds"):
            detail["fica_de_fora"] = _OUTSIDE_AVAILABLE
        return ValueNode(kind="input", label=label, value=seconds, children=children, detail=detail)

    @staticmethod
    def _base_parts(key, bases, hours, total_exception=False) -> list[tuple[str, float, str | None]]:
        """Categorias de tempo que formam a base, lidas do mesmo overview."""

        if total_exception and key in ("available_seconds", "operational_seconds"):
            # Na regra do período todo sem demanda o calculador põe o tempo sem
            # demanda como disponível (``_no_demand_exception``).
            return [("Recurso sem demanda", _base(bases, key), "tempo.sem_demanda")]

        worked = [
            ("Produção", _base(hours, "production_seconds"), "tempo.producao"),
            ("Setup", _base(hours, "setup_seconds"), "tempo.setup"),
            ("Retrabalho", _base(hours, "rework_seconds"), "tempo.retrabalho"),
            ("Atividade sem OP", _base(hours, "activity_without_op_seconds"), "tempo.atividade_sem_op"),
        ]
        if key == "worked_seconds":
            return worked
        if key in ("available_seconds", "operational_seconds"):
            if not _base(bases, key) and not any(part[1] for part in worked):
                return []
            unplanned = _base(hours, "unplanned_downtime_seconds")
            # Sem identificação não tem chave própria no overview: é o resto do
            # disponível depois do trabalhado e da parada não planejada.
            unknown = _base(bases, key) - _base(bases, "worked_seconds") - unplanned
            return [
                ("Tempo trabalhado", _base(bases, "worked_seconds"), None),
                ("Parada não planejada", unplanned, "tempo.parada_nao_planejada"),
                ("Sem identificação (estado desconhecido)", max(0.0, unknown), None),
            ]
        if key == "productive_net_seconds":
            return [
                ("Tempo padrão das peças boas", _base(bases, "standard_run_seconds"), None),
                *worked[1:],
            ]
        if key == "productive_gross_seconds":
            return [worked[0]]
        return []

    @staticmethod
    def _outside_available(hours, total_exception=False, no_demand_listed=0.0) -> list[dict]:
        def seconds(key):
            base = _base(hours, key)
            return max(0.0, base - no_demand_listed) if key == "no_demand_seconds" else base

        items = (
            ("Parada planejada", "planned_downtime_seconds",
             "Parada combinada (intervalo, reunião, limpeza) sai do tempo disponível."),
            ("Recurso sem demanda", "no_demand_seconds",
             "Recurso no turno sem OP para fazer não conta como tempo disponível."),
            ("Fila", "queue_seconds",
             "Tempo de espera na fila não entra no tempo disponível."),
            ("Fora de turno", "out_of_shift_seconds",
             "Fora do turno cadastrado não é tempo disponível."),
        )
        return [
            {
                "label": label,
                "value": seconds(key),
                "unidade": "segundos",
                "reason": f"{reason} ({_hms(seconds(key))})",
            }
            for label, key, reason in items
            if seconds(key) and not (total_exception and key == "no_demand_seconds")
        ]

    # -------------------------------------------------------------------- OEE

    def _explain_oee(self, overview, value, shown, resources, sectors, max_leaves):
        kpis = overview.get("kpis") or {}
        components = []
        component_values = []
        for key, label, link in _COMPONENTS:
            metric_value = kpis.get(key) or {}
            raw = metric_value.get("value")
            component_value = float(raw) if raw is not None else None
            component_values.append(component_value)
            components.append(ValueNode(
                kind="input",
                label=label,
                value=component_value,
                detail={
                    "unidade": "%",
                    "valor": _pct(component_value),
                    "metric": link,
                    **({"motivo": metric_value["reason"]} if metric_value.get("reason") else {}),
                },
            ))

        product = (
            component_values[0] * component_values[1] * component_values[2] / 10000.0
            if all(item is not None for item in component_values)
            else None
        )
        exception = _is_no_demand(overview.get("kpi_calculation"))
        if exception:
            reconciliation = {"ok": True, "sum": value, "diff": 0.0, "method": "regra_sem_demanda"}
        elif value is None:
            reconciliation = {
                "ok": product is None,
                "sum": product,
                "diff": None,
                "method": "produto_dos_componentes",
            }
        else:
            reconciliation = {
                "ok": product is not None and abs(product - value) <= _TOLERANCE,
                "sum": product,
                "diff": (product - value) if product is not None else None,
                "method": "produto_dos_componentes",
            }

        if value is None:
            reason = shown.get("reason") or "OEE indisponível no filtro."
            return components, reason, reconciliation

        d, p, f = (_pct(item) for item in component_values)
        reason = (
            str(shown.get("reason") or "Período todo sem demanda: OEE 0% pela regra corporativa.")
            if exception
            else f"{d} de Disponibilidade × {p} de Performance × {f} de FTT = {_pct(value)}."
        )
        children = components + self._sector_nodes(KPI_TEXT["kpi.oee"], sectors, resources, max_leaves)
        return children, reason, reconciliation

    # ------------------------------------------------------- setor > recurso

    def _sector_nodes(self, text, sectors, resources, max_leaves) -> list[ValueNode]:
        by_sector: dict[str, list[dict]] = {}
        for row in resources:
            by_sector.setdefault(str(row.get("sector") or "").strip() or _NO_SECTOR, []).append(row)
        sector_rows = {str(row.get("setor") or "").strip() or _NO_SECTOR: row for row in sectors}

        nodes = []
        for name in list(sector_rows) + [name for name in by_sector if name not in sector_rows]:
            members = by_sector.get(name, [])
            sector_row = sector_rows.get(name)
            if sector_row is None and not members:
                continue
            resource_nodes = [self._entity_node("resource", row.get("resource") or _NO_RESOURCE, row, text)
                              for row in members]
            resource_nodes.sort(key=_node_order)
            kept, rest = resource_nodes[:max_leaves], resource_nodes[max_leaves:]
            if rest:
                kept.append(ValueNode(
                    kind="resource",
                    label=f"Outros {len(rest)} recursos" if len(rest) > 1 else "Outro recurso",
                    value=None,
                    truncated=True,
                ))
            if sector_row is not None:
                node = self._entity_node("sector", name, sector_row, text)
            else:
                node = ValueNode(kind="sector", label=name, value=None, detail={
                    "motivo": "O setor destes recursos não tem linha própria no cálculo por setor.",
                })
            node.children = kept
            node.truncated = bool(rest)
            nodes.append(node)
        nodes.sort(key=_node_order)
        return nodes

    def _entity_node(self, kind, label, row, text) -> ValueNode:
        bases = row.get("kpi_time_bases") or {}
        metrics = row.get("metrics") or {}
        calculation = row.get("kpi_calculation") or {}
        exception = _is_no_demand(calculation)
        detail: dict[str, Any] = {}

        if text["metric_key"] == "oee":
            metric = metrics.get("oee") or {}
            raw = metric.get("value")
            value = float(raw) if raw is not None else None
            parts = [(metrics.get(key) or {}).get("value") for key, _l, _m in _COMPONENTS]
            detail["disponibilidade"] = _pct(parts[0])
            detail["performance"] = _pct(parts[1])
            detail["ftt"] = _pct(parts[2])
            if value is not None and not exception:
                detail["conta"] = f"{_pct(parts[0])} × {_pct(parts[1])} × {_pct(parts[2])} = {_pct(value)}"
        else:
            num_key, den_key = text["numerator"], text["denominator"]
            numerator, denominator = _base(bases, num_key), _base(bases, den_key)
            detail[_BASE_DETAIL_KEY[num_key]] = _time_text(numerator)
            detail[_BASE_DETAIL_KEY[den_key]] = _time_text(denominator)
            if text["metric_key"] is not None:
                metric = metrics.get(text["metric_key"]) or {}
                raw = metric.get("value")
                value = float(raw) if raw is not None else None
            else:
                metric = {}
                value = None if exception else _ratio(numerator, denominator)
            if value is not None and not exception:
                detail["conta"] = f"{_hms(numerator)} ÷ {_hms(denominator)} = {_pct(value)}"

        if exception:
            detail["regra"] = (
                "Período todo sem demanda: regra corporativa (Disponibilidade 100%, "
                "Performance 0%, OEE 0%); o tempo não entra no total."
            )
            detail["tempo_sem_demanda"] = _time_text(_base(bases, "no_demand_seconds"))
        elif metric.get("reason"):
            detail["motivo"] = metric["reason"]
        if PERFORMANCE_ABOVE_LIMIT_ALERT in (calculation.get("alerts") or []):
            detail["alerta"] = "Performance acima de 100%"
        return ValueNode(kind=kind, label=str(label), value=value, detail=detail)

    # ------------------------------------------------------------------ notas

    def _common_notes(
        self, metric, text, overview, shown, value, calculation, resources, sectors,
        total_exception, exception_resources, notes,
    ):
        rule_version = calculation.get("rule_version") or OEE_RULE_VERSION
        if total_exception:
            notes.append(
                "Todo o período ficou sem demanda: pela regra corporativa (versão "
                f"{rule_version}, origem {RESULT_ORIGIN_NO_DEMAND}) a Disponibilidade "
                "é 100%, a Performance 0%, o OEE 0% e o FTT não existe. O número "
                "vem da regra, não da conta das horas."
            )
        elif exception_resources:
            names = ", ".join(str(row.get("resource") or _NO_RESOURCE) for row in exception_resources)
            notes.append(
                f"{len(exception_resources)} recurso(s) ficaram o período todo sem "
                f"demanda ({names}). Pela regra corporativa (versão {rule_version}, "
                f"origem {RESULT_ORIGIN_NO_DEMAND}) cada um mostra Disponibilidade "
                "100%, Performance 0% e OEE 0%, mas o tempo deles não entra na conta do total."
            )

        uses_performance = metric in ("kpi.oee", "kpi.performance", "kpi.ae")
        if uses_performance and PERFORMANCE_ABOVE_LIMIT_ALERT in (calculation.get("alerts") or []):
            notes.append(
                f"Alerta {PERFORMANCE_ABOVE_LIMIT_ALERT}: a Performance do total passou "
                "de 100%. O valor aparece sem corte; investigar tempo padrão, unidade, "
                "OPs ao mesmo tempo ou apontamento duplicado."
            )
        if uses_performance:
            high = [
                str(row.get("resource") or _NO_RESOURCE)
                for row in resources
                if PERFORMANCE_ABOVE_LIMIT_ALERT in ((row.get("kpi_calculation") or {}).get("alerts") or [])
            ]
            if high:
                notes.append(f"Recursos com Performance acima de 100%: {', '.join(high)}.")
            without_standard = sum(int(row.get("pecas_boas_sem_tempo_padrao") or 0) for row in sectors)
            if without_standard:
                notes.append(
                    f"{without_standard} peça(s) boa(s) sem tempo padrão cadastrado: o "
                    "tempo delas não soma no numerador, e a Performance fica menor do que a real."
                )
            estimated = overview.get("kpis_estimados") or {}
            estimated_value = (estimated.get("performance") or {}).get("value")
            if estimated.get("usa_tempo_estimado") and estimated_value is not None:
                notes.append(
                    "A Performance oficial usa só o tempo padrão do Protheus e o manual. "
                    f"Com o tempo estimado pelo Gestor para {estimated.get('pecas_boas_tempo_estimado') or 0} "
                    f"peça(s), ela seria {_pct(float(estimated_value))}."
                )

        if value is not None and shown.get("reason") and not total_exception:
            notes.append(str(shown["reason"]))
        if metric == "kpi.oee":
            notes.append(_NOTE_FTT)
        if metric == "kpi.utilizacao":
            notes.append(_NOTE_UTILIZATION_EQUALS_AVAILABILITY)
        if text["metric_key"] is None and value is not None:
            notes.append(_NOTE_RESOURCE_RATIO)


def _node_order(node: ValueNode):
    return (node.value is None, -(node.value or 0.0), node.label.casefold())
