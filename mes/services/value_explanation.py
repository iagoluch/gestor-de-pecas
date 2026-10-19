"""Explicação de valor: de onde vêm as peças boas, o refugo, o retrabalho e as taxas.

Contrato: ``docs/superpowers/specs/2026-10-19-explicacao-valor-contrato.md``.

O serviço não tem conta própria. O número explicado é o de
``ManagementService.get_overview`` (``production`` e ``kpis.ftt``), o mesmo da
tela. A árvore (setor -> recurso -> lançamento) é montada com as MESMAS linhas
que o overview somou (``ManagementService.quantity_sources``), e a
``reconciliation`` confere uma contra o outro: se as duas pontas divergirem um
dia, a divergência aparece em vez de ficar escondida.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

from mes.contracts import AnalyticsFilter
from mes.services.metric_explanation import UnknownMetricError


# Folhas reais por recurso; o excedente vira um nó "Outros N registros".
MAX_LEAVES_PER_RESOURCE = 200
_TOLERANCE = 1e-6
_NO_SECTOR = "Não informado"
_NO_RESOURCE = "Sem recurso informado"
_QUANTITY_KINDS = ("boa", "refugo", "retrabalho")

_NOTE_PERIOD = (
    "Os totais da Visão Geral e da Produção realizada vêm dos lançamentos de "
    "quantidade do período. As tabelas Produção > OPs e Planejado x Realizado "
    "somam os apontamentos por OP, sem restringir ao período, e podem mostrar "
    "números diferentes."
)
_NOTE_RATES = (
    "A taxa de refugo ignora o retrabalho (refugo ÷ boas + refugo); o FTT "
    "inclui o retrabalho na base (boas ÷ boas + refugo + retrabalho). Por isso "
    "os dois percentuais usam bases diferentes."
)
_NOTE_FALLBACK = (
    "Não há fonte de lançamentos de quantidade disponível; a Visão Geral usa a "
    "quantidade dos apontamentos que tocam o período, e esta explicação usa a "
    "mesma fonte."
)
_NOTE_CUTTING = (
    "As peças boas do Corte não vêm dos lançamentos de quantidade: vêm das "
    "tarefas de corte concluídas no período e entram no total da Visão Geral."
)

VALUE_TEXT: dict[str, dict[str, str]] = {
    "qtd.boa": {
        "label": "Peças boas",
        "unit": "pcs",
        "kind": "boa",
        "reason": "Peças que foram lançadas como boas no período e nos filtros escolhidos.",
        "rule": (
            "Soma das quantidades lançadas como boas (production.good). Refugo e "
            "retrabalho não entram."
        ),
    },
    "qtd.refugo": {
        "label": "Refugo",
        "unit": "pcs",
        "kind": "refugo",
        "reason": "Peças perdidas, lançadas como refugo no período e nos filtros escolhidos.",
        "rule": (
            "Soma das quantidades lançadas como refugo (production.scrap). Cada "
            "lançamento mostra o motivo informado, quando existe."
        ),
    },
    "qtd.retrabalho": {
        "label": "Retrabalho",
        "unit": "pcs",
        "kind": "retrabalho",
        "reason": "Peças que voltaram para ser refeitas, lançadas no período e nos filtros escolhidos.",
        "rule": (
            "Soma das quantidades lançadas como retrabalho (production.rework). "
            "Peça em retrabalho não conta como boa de primeira passagem."
        ),
    },
    "qtd.taxa_refugo": {
        "label": "Taxa de refugo",
        "unit": "pct",
        "kind": None,
        "reason": "Quanto das peças que fecharam como boas ou refugo foi refugo.",
        "rule": "Refugo ÷ (boas + refugo) × 100. O retrabalho não entra nesta conta.",
    },
    "qtd.ftt": {
        "label": "FTT (aprovadas de primeira)",
        "unit": "pct",
        "kind": None,
        "reason": "Quanto da produção ficou pronta de primeira, sem refugo e sem retrabalho.",
        "rule": "Boas ÷ (boas + refugo + retrabalho) × 100. O retrabalho entra na base.",
    },
}

# Chave de cada tipo em ``get_overview()["production"]``.
_FIELD = {"boa": "good", "refugo": "scrap", "retrabalho": "rework"}
_LABEL_BY_KIND = {"boa": "Peças boas", "refugo": "Refugo", "retrabalho": "Retrabalho"}
_METRIC_BY_KIND = {"boa": "qtd.boa", "refugo": "qtd.refugo", "retrabalho": "qtd.retrabalho"}
_EXCLUDED_REASON = {
    ("boa", "refugo"): "Peça refugada não conta como boa.",
    ("boa", "retrabalho"): "Peça em retrabalho não conta como boa de primeira passagem.",
    ("refugo", "boa"): "Peça boa não é refugo.",
    ("refugo", "retrabalho"): "Peça em retrabalho não é refugo; ela volta para ser refeita.",
    ("retrabalho", "boa"): "Peça boa não é retrabalho.",
    ("retrabalho", "refugo"): "Peça refugada não volta para retrabalho; ela é perda.",
}


@dataclass
class ValueNode:
    kind: str  # "sector" | "resource" | "op" | "event" | "part" | "input"
    label: str
    value: float | None
    children: list["ValueNode"] = field(default_factory=list)
    detail: dict[str, Any] | None = None
    truncated: bool = False


@dataclass
class ValueExplanation:
    metric: str
    label: str
    unit: str
    value: float | None
    reason: str
    rule: str
    children: list[ValueNode]
    excluded: list[dict]
    reconciliation: dict
    calculated_at: str
    truncated: bool
    notes: list[str] = field(default_factory=list)
    kind: str = "value"

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class _Leaf:
    node_kind: str
    label: str
    value: float
    stamp: str
    detail: dict[str, Any]


def _iso(value: Any) -> str:
    if value is None:
        return ""
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def _text(value: Any) -> str:
    return str(value or "").strip()


def _detail(**fields: Any) -> dict[str, Any]:
    """Só os campos que existem no registro: nunca inventa chave vazia."""

    return {key: value for key, value in fields.items() if value not in (None, "")}


def _stamp_label(prefix: str, stamp: str) -> str:
    if len(stamp) >= 16 and stamp[4:5] == "-":
        return f"{prefix} · {stamp[8:10]}/{stamp[5:7]} {stamp[11:16]}"
    return prefix


class ValueExplanationService:
    def __init__(self, management, repository):
        self.management = management
        # Reservado, como em ``MetricExplanationService``: hoje tudo vem do
        # ``management`` (mesmas leituras do overview).
        self.repository = repository

    def explain(
        self,
        metric: str,
        filters: AnalyticsFilter,
        *,
        max_leaves: int = MAX_LEAVES_PER_RESOURCE,
    ) -> ValueExplanation:
        text = VALUE_TEXT.get(metric)
        if text is None:
            raise UnknownMetricError(f"Métrica desconhecida: {metric!r}")

        overview = self.management.get_overview(filters)
        production = overview["production"]
        sources = self.management.quantity_sources(filters)
        fallback = not sources["available"]
        totals = {kind: int(production.get(_FIELD[kind]) or 0) for kind in _QUANTITY_KINDS}

        cutting_used = False
        notes: list[str] = []
        if text["kind"] is not None:
            kind = text["kind"]
            groups, cutting_used, unknown = self._collect(sources, kind)
            children = _sector_nodes(groups, max_leaves)
            value: float | None = float(totals[kind])
            total_sum = sum(node.value or 0.0 for node in children)
            reconciliation = _reconciliation(value, total_sum)
            reason = (
                text["reason"]
                if children
                else (
                    production.get("reason")
                    or f"Nenhum lançamento de {text['label'].lower()} no período e nos filtros escolhidos."
                )
            )
            excluded = [
                {
                    "label": _LABEL_BY_KIND[other],
                    "value": float(totals[other]),
                    "reason": _EXCLUDED_REASON[(kind, other)],
                }
                for other in _QUANTITY_KINDS
                if other != kind and totals[other]
            ]
            if unknown:
                excluded.append({
                    "label": "Lançamentos de tipo desconhecido",
                    "value": float(unknown),
                    "reason": "O tipo não é boa, refugo nem retrabalho; o overview também não soma.",
                })
        else:
            cutting_used = bool(self._cutting_rows(sources))
            value, children, reason, reconciliation = self._rate(
                metric, text, overview, totals
            )
            excluded = (
                [{
                    "label": "Retrabalho",
                    "value": float(totals["retrabalho"]),
                    "reason": "O retrabalho não entra na taxa de refugo.",
                }]
                if metric == "qtd.taxa_refugo" and totals["retrabalho"]
                else []
            )

        if metric in ("qtd.taxa_refugo", "qtd.ftt"):
            notes.append(_NOTE_RATES)
        notes.append(_NOTE_PERIOD)
        if fallback:
            notes.append(_NOTE_FALLBACK)
        if cutting_used and metric in ("qtd.boa", "qtd.taxa_refugo", "qtd.ftt"):
            notes.append(_NOTE_CUTTING)

        return ValueExplanation(
            metric=metric,
            label=text["label"],
            unit=text["unit"],
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

    # ------------------------------------------------------------------ dados

    def _now(self) -> datetime:
        clock = getattr(self.management, "_now", None)
        value = clock() if callable(clock) else datetime.now()
        return value if isinstance(value, datetime) else datetime.now()

    @staticmethod
    def _cutting_rows(sources: dict) -> list[dict]:
        """Linhas do Corte que o overview soma às boas (mesmo predicado dele)."""

        rows = []
        for row in sources.get("cutting") or []:
            qty = max(0, int(row.get("quantidade") or 0))
            if qty and _text(row.get("codigo_op")):
                rows.append(row)
        return rows

    def _collect(self, sources: dict, kind: str):
        """Agrupa os lançamentos de um tipo em setor -> recurso -> folhas."""

        groups: dict[str, dict[str, dict]] = defaultdict(dict)
        unknown = 0

        def add(sector: str, resource: str, leaf: _Leaf) -> None:
            key = resource.casefold()
            bucket = groups[sector].setdefault(key, {"name": resource, "leaves": []})
            bucket["leaves"].append(leaf)

        if sources["available"]:
            for event in sources["events"]:
                qty = int(event.get("quantidade") or 0)
                event_kind = _text(event.get("tipo")).lower()
                if event_kind not in _QUANTITY_KINDS:
                    unknown += qty
                    continue
                if event_kind != kind:
                    continue
                stamp = _iso(event.get("data_hora"))
                add(
                    _text(event.get("tipo_setor")) or _NO_SECTOR,
                    _text(event.get("recurso")) or _NO_RESOURCE,
                    _Leaf(
                        "event",
                        _stamp_label(
                            f"OP {_text(event.get('op'))}" if _text(event.get("op")) else "Sem OP",
                            stamp,
                        ),
                        float(qty),
                        stamp,
                        _detail(
                            id=event.get("id"),
                            op=_text(event.get("op")),
                            operador=_text(event.get("operador")),
                            data_hora=stamp,
                            motivo=_text(event.get("motivo")),
                            causa_raiz=_text(event.get("causa_raiz")),
                            origem=_text(event.get("origem")),
                        ),
                    ),
                )
        else:
            column = f"quantidade_{kind}"
            for fact in sources["facts"]:
                qty = int(fact.get(column) or 0)
                if not qty:
                    continue
                stamp = _iso(fact.get("data_inicio"))
                add(
                    _text(fact.get("tipo_setor")) or _NO_SECTOR,
                    _text(fact.get("maquina")) or _NO_RESOURCE,
                    _Leaf(
                        "event",
                        _stamp_label(
                            f"OP {_text(fact.get('op'))}" if _text(fact.get("op")) else "Sem OP",
                            stamp,
                        ),
                        float(qty),
                        stamp,
                        _detail(
                            id=fact.get("id"),
                            op=_text(fact.get("op")),
                            operador=_text(fact.get("operador_inicio_nome")),
                            data_hora=stamp,
                            origem="apontamentos_operacionais",
                        ),
                    ),
                )

        cutting_used = False
        if kind == "boa":
            for row in self._cutting_rows(sources):
                cutting_used = True
                stamp = _iso(row.get("concluido_em"))
                op = _text(row.get("codigo_op"))
                add(
                    "Corte",
                    _text(row.get("maquina")) or _NO_RESOURCE,
                    _Leaf(
                        "op",
                        _stamp_label(f"OP {op}", stamp),
                        float(max(0, int(row.get("quantidade") or 0))),
                        stamp,
                        _detail(
                            op=op,
                            tarefa=_text(row.get("codigo_tarefa")),
                            data_hora=stamp,
                            origem="apontamentos_corte",
                        ),
                    ),
                )
        return groups, cutting_used, unknown

    # ------------------------------------------------------------------ taxas

    def _rate(self, metric: str, text: dict, overview: dict, totals: dict):
        good, scrap, rework = totals["boa"], totals["refugo"], totals["retrabalho"]
        inputs = [_input_node("boa", good), _input_node("refugo", scrap)]
        if metric == "qtd.taxa_refugo":
            base = good + scrap
            value = scrap / base * 100.0 if base > 0 else None
            recomposed = value
            reason = (
                f"{scrap} peças de refugo em {base} fechadas (boas + refugo)."
                if base > 0
                else "Não há peças boas nem refugo no período, então a taxa não existe."
            )
        else:
            inputs.append(_input_node("retrabalho", rework))
            ftt = (overview.get("kpis") or {}).get("ftt") or {}
            raw = ftt.get("value")
            value = float(raw) if raw is not None else None
            base = good + scrap + rework
            recomposed = good / base * 100.0 if base > 0 else None
            reason = (
                f"{good} peças boas em {base} (boas + refugo + retrabalho)."
                if base > 0
                else (
                    ftt.get("reason")
                    or "Não há peças boas, refugo nem retrabalho no período, então o FTT não existe."
                )
            )
        reconciliation = {
            "ok": (
                recomposed is None
                if value is None
                else recomposed is not None and abs(recomposed - value) <= _TOLERANCE
            ),
            "sum": recomposed,
            "diff": (recomposed - value) if value is not None and recomposed is not None else None,
        }
        return value, inputs, reason, reconciliation




def _input_node(kind: str, value: int) -> ValueNode:
    return ValueNode(
        kind="input",
        label=_LABEL_BY_KIND[kind],
        value=float(value),
        detail={"metric": _METRIC_BY_KIND[kind]},
    )


def _reconciliation(value: float | None, total_sum: float) -> dict:
    diff = total_sum - (value or 0.0)
    return {"ok": abs(diff) <= _TOLERANCE, "sum": total_sum, "diff": diff}


def _any_truncated(nodes: list[ValueNode]) -> bool:
    return any(node.truncated or _any_truncated(node.children) for node in nodes)


def _resource_node(name: str, leaves: list[_Leaf], max_leaves: int) -> ValueNode:
    leaves = sorted(leaves, key=lambda leaf: leaf.stamp, reverse=True)
    leaves.sort(key=lambda leaf: -leaf.value)  # estável: maiores primeiro, recentes antes
    kept, rest = leaves[:max_leaves], leaves[max_leaves:]
    children = [
        ValueNode(kind=leaf.node_kind, label=leaf.label, value=leaf.value, detail=leaf.detail)
        for leaf in kept
    ]
    if rest:
        children.append(
            ValueNode(
                kind="event",
                label=f"Outros {len(rest)} registros" if len(rest) > 1 else "Outro registro",
                value=sum(leaf.value for leaf in rest),
                truncated=True,
            )
        )
    return ValueNode(
        kind="resource",
        label=name,
        value=sum(leaf.value for leaf in leaves),
        children=children,
        truncated=bool(rest),
    )


def _sector_nodes(groups: dict[str, dict[str, dict]], max_leaves: int) -> list[ValueNode]:
    sectors = []
    for sector, resources in groups.items():
        nodes = [
            _resource_node(bucket["name"], bucket["leaves"], max_leaves)
            for bucket in resources.values()
        ]
        nodes.sort(key=lambda node: (-(node.value or 0.0), node.label.casefold()))
        sectors.append(
            ValueNode(
                kind="sector",
                label=sector,
                value=sum(node.value or 0.0 for node in nodes),
                children=nodes,
            )
        )
    sectors.sort(key=lambda node: (-(node.value or 0.0), node.label.casefold()))
    return sectors
