"""Explicação das métricas de tempo: do total até o trecho que o formou.

O serviço não tem conta própria. Ele lê ``ManagementService.physical_consolidation``
(a mesma consolidação que ``get_overview`` publica) e organiza os segmentos
consolidados em setor -> recurso -> trecho. O total de cada métrica é o mesmo
número que o overview mostra; a árvore só prova de onde ele vem.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

from mes.contracts import AnalyticsFilter
from mes.analytics.resource_state import physical_state_category
from mes.domain import EventCategory, StopClassification


DEFAULT_MAX_NODES = 400
# Tolerância da conferência setor x total (ruído de soma em ponto flutuante).
_RECONCILIATION_TOLERANCE_SECONDS = 0.01
_STATE_REF_PREFIX = "estado_recurso:"


class UnknownMetricError(ValueError):
    """Identificador de métrica fora da lista de métricas de tempo explicáveis."""


# Texto em português simples, por métrica. ``reason`` é a frase de motivo do
# painel; ``rule`` é a regra de como o número é montado.
RULE_TEXT: dict[str, dict[str, str]] = {
    "tempo.producao": {
        "label": "Produção",
        "reason": "Tempo em que o recurso esteve produzindo.",
        "rule": (
            "Cada recurso conta uma vez só por instante. Duas OPs produzindo ao "
            "mesmo tempo na mesma máquina não dobram as horas. Se uma OP produz "
            "e outra está parada, vale produção."
        ),
    },
    "tempo.setup": {
        "label": "Setup",
        "reason": "Tempo em que o recurso esteve sendo preparado para produzir.",
        "rule": "Cada recurso conta uma vez só por instante, como na produção.",
    },
    "tempo.sem_demanda": {
        "label": "Recurso sem demanda",
        "reason": (
            "Nenhuma OP foi apontada nestes recursos nestes horários, então "
            "ficaram esperando serviço."
        ),
        "rule": (
            "Conta o tempo em que o recurso estava no turno, sem OP. Não é fila, "
            "não é parada e não é fora de turno."
        ),
    },
    "tempo.parada_planejada": {
        "label": "Parada planejada",
        "reason": "Paradas combinadas ou previstas, como intervalo e reunião.",
        "rule": (
            "Parada cuja classificação é planejada. Se duas fontes discordam da "
            "classificação, o trecho vai para parada não planejada."
        ),
    },
    "tempo.parada_nao_planejada": {
        "label": "Parada não planejada",
        "reason": "Paradas que ninguém previu, como falta de material ou quebra.",
        "rule": (
            "Parada cuja classificação é não planejada. Quando duas fontes "
            "discordam da classificação, o sistema fica com a não planejada para "
            "não esconder perda."
        ),
    },
    "tempo.a_esclarecer": {
        "label": "Tempo a esclarecer",
        "reason": (
            "Dois registros do mesmo recurso disseram coisas diferentes ao mesmo "
            "tempo, e o sistema não escolheu um."
        ),
        "rule": (
            "Estados incompatíveis no mesmo recurso e no mesmo instante ficam "
            "aqui, em linha própria, em vez de caírem em produção ou parada."
        ),
    },
    "tempo.fora_turno": {
        "label": "Fora de turno",
        "reason": "Horas fora do turno cadastrado dos recursos.",
        "rule": (
            "É um número do calendário: o mesmo horário visto em vários recursos "
            "conta uma vez só, sem soma e sem média por recurso."
        ),
    },
    "tempo.retrabalho": {
        "label": "Retrabalho",
        "reason": "Tempo em que o recurso esteve refazendo peças.",
        "rule": "Cada recurso conta uma vez só por instante.",
    },
    "tempo.atividade_sem_op": {
        "label": "Atividade sem OP",
        "reason": "Tempo de atividades do recurso que não estavam ligadas a uma OP.",
        "rule": "Cada recurso conta uma vez só por instante.",
    },
}

_EMPTY_REASON = "Nenhum registro no período."
_EMPTY_METRIC_REASON = "Nenhum registro desta métrica no período."
_LEGACY_NESTING_LABEL = "Apontamento de nesting sem horário de início/fim"

_RULE_APPLIED_TEXT = {
    "production_prevailed": "Produção e parada ao mesmo tempo: vale produção.",
    "state_conflict": "Estados incompatíveis ao mesmo tempo: fica a esclarecer.",
    "reclassified_to_unplanned": (
        "Fontes discordaram se a parada era planejada: contada como não planejada."
    ),
}

_CATEGORY_LABEL = {
    EventCategory.PRODUCTION: "Produção",
    EventCategory.SETUP: "Setup",
    EventCategory.NO_DEMAND: "Recurso sem demanda",
    EventCategory.QUEUE: "Fila",
    EventCategory.REWORK: "Retrabalho",
    EventCategory.ACTIVITY_WITHOUT_OP: "Atividade sem OP",
    EventCategory.OUT_OF_SHIFT: "Fora de turno",
    EventCategory.UNKNOWN: "Sem classificação",
}

_EXCLUDED_REASON = {
    "Parada planejada": "Conta como parada planejada, não nesta linha.",
    "Parada não planejada": "Conta como parada não planejada, não nesta linha.",
    "Tempo a esclarecer": "Registros incompatíveis no mesmo instante; fica em linha própria.",
}

_CATEGORY_BY_METRIC = {
    "tempo.producao": EventCategory.PRODUCTION,
    "tempo.setup": EventCategory.SETUP,
    "tempo.sem_demanda": EventCategory.NO_DEMAND,
    "tempo.fora_turno": EventCategory.OUT_OF_SHIFT,
    "tempo.retrabalho": EventCategory.REWORK,
    "tempo.atividade_sem_op": EventCategory.ACTIVITY_WITHOUT_OP,
}

# Linhas irmãs mostradas junto do número ("X de Y do turno").
_SIBLING_METRICS = (
    "tempo.producao",
    "tempo.setup",
    "tempo.sem_demanda",
    "tempo.parada_planejada",
    "tempo.parada_nao_planejada",
    "tempo.a_esclarecer",
)

# Métricas sem média por recurso (grandeza de calendário).
_NO_AVERAGE_METRICS = {"tempo.fora_turno"}


@dataclass
class Node:
    kind: str  # "sector" | "resource" | "stretch"
    label: str
    seconds: float
    children: list["Node"] = field(default_factory=list)
    detail: dict[str, Any] | None = None
    # Verdadeiro quando filhos foram omitidos sem caber um nó "outros N ...".
    truncated: bool = False


@dataclass
class ExplanationTree:
    metric: str
    label: str
    total_seconds: float
    average_seconds: float | None
    resource_count: int
    day_count: int
    parent_total_seconds: float
    siblings: list[dict]
    reason: str
    rule: str
    children: list[Node]
    excluded: list[dict]
    reconciliation: dict
    calculated_at: str
    truncated: bool
    # Avisos curtos para o painel (ex.: recursos sem turno que entram no total
    # mas não na média).
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


class MetricExplanationService:
    def __init__(self, management, repository):
        self.management = management
        # Reservado: hoje tudo vem de ``management.physical_consolidation``
        # (estados já lidos, sem nova consulta).
        self.repository = repository

    def explain(
        self,
        metric: str,
        filters: AnalyticsFilter,
        *,
        max_nodes: int = DEFAULT_MAX_NODES,
    ) -> ExplanationTree:
        if metric not in RULE_TEXT:
            raise UnknownMetricError(f"Métrica desconhecida: {metric!r}")

        consolidation = self.management.physical_consolidation(filters)
        consolidated = consolidation["consolidated"]
        segments = consolidated["segments"]
        calendar_resources = consolidation["calendar_resources"]
        text = RULE_TEXT[metric]

        selected = [seg for seg in segments if _belongs(metric, seg)]
        rows = {
            str(row.get("id")): dict(row)
            for row in consolidation.get("state_rows") or ()
        }
        # Leitura legada (sem estado canônico): o overview soma à produção os
        # nestings que só conhecem a duração; a explicação precisa fechar com ele.
        legacy = consolidation.get("legacy_without_interval") or []
        legacy_seconds = sum(item["seconds"] for item in legacy)
        legacy_production = legacy if metric == "tempo.producao" else []
        total = _official_total(metric, consolidated) + (
            legacy_seconds if metric == "tempo.producao" else 0.0
        )

        by_sector: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))
        for seg in selected:
            by_sector[seg.sector][seg.resource].append(seg)

        multi_day = consolidation["days"] > 1
        sector_nodes = [
            _sector_node(sector, resources, rows, multi_day)
            for sector, resources in by_sector.items()
        ]
        _add_legacy_nesting(sector_nodes, legacy_production)
        sector_nodes.sort(key=_by_seconds)
        children, truncated = _truncate(sector_nodes, max_nodes)

        duplicated = (
            float(consolidated.get("out_of_shift_duplicated_seconds", 0.0))
            if metric == "tempo.fora_turno"
            else 0.0
        )
        sum_seconds = sum(node.seconds for node in children) - duplicated
        diff = sum_seconds - total
        reconciliation = {
            "ok": abs(diff) <= _RECONCILIATION_TOLERANCE_SECONDS,
            "sum_seconds": sum_seconds,
            "diff_seconds": diff,
        }

        resource_count = len(calendar_resources)
        average = (
            None
            if metric in _NO_AVERAGE_METRICS or resource_count == 0
            else total / resource_count
        )

        excluded = self._excluded(metric, segments, selected, rows, duplicated)
        notes = _no_calendar_notes(metric, selected, calendar_resources)

        # ``measured_seconds`` do overview inclui os nestings legados.
        in_shift = (
            float(consolidated["physical_seconds"])
            - float(consolidated.get("out_of_shift_attributed_seconds", 0.0))
            + legacy_seconds
        )
        if metric == "tempo.fora_turno":
            parent_total = float(consolidated["physical_seconds"]) + legacy_seconds
            siblings: list[dict] = []
        else:
            parent_total = in_shift
            siblings = [
                {
                    "metric": sibling,
                    "label": RULE_TEXT[sibling]["label"],
                    "seconds": _official_total(sibling, consolidated)
                    + (legacy_seconds if sibling == "tempo.producao" else 0.0),
                }
                for sibling in _SIBLING_METRICS
            ]

        calculated_at = consolidation["calculated_at"]
        return ExplanationTree(
            metric=metric,
            label=text["label"],
            total_seconds=total,
            average_seconds=average,
            resource_count=resource_count,
            day_count=consolidation["days"],
            parent_total_seconds=parent_total,
            siblings=siblings,
            reason=(
                text["reason"]
                if selected or legacy_production
                else _EMPTY_METRIC_REASON
                if segments or legacy
                else _EMPTY_REASON
            ),
            rule=text["rule"],
            children=children,
            excluded=excluded,
            reconciliation=reconciliation,
            calculated_at=(
                calculated_at.isoformat()
                if isinstance(calculated_at, datetime)
                else str(calculated_at)
            ),
            truncated=truncated,
            notes=notes,
        )

    def _excluded(self, metric, segments, selected, rows, duplicated) -> list[dict]:
        """Tempo dos mesmos recursos que ficou de fora desta métrica, com motivo."""

        result = []
        if metric == "tempo.fora_turno":
            if duplicated > 0:
                result.append({
                    "label": "Mesmo horário visto em vários recursos",
                    "seconds": duplicated,
                    "reason": (
                        "O fora de turno é do calendário: o mesmo horário em "
                        "vários recursos conta uma vez só."
                    ),
                })
            return result

        resources = {seg.resource for seg in selected}
        buckets: dict[tuple[str, str | None], float] = defaultdict(float)
        for seg in segments:
            if (
                seg.resource not in resources
                or _belongs(metric, seg)
                or seg.category is EventCategory.OUT_OF_SHIFT
            ):
                continue
            label = _bucket_label(seg)
            motivo = _motivo(seg, rows) if seg.category is EventCategory.DOWNTIME else None
            buckets[(label, motivo)] += seg.seconds

        for (label, motivo), seconds in sorted(
            buckets.items(), key=lambda item: (-item[1], item[0][0])
        ):
            result.append({
                "label": f"{label}: {motivo}" if motivo else label,
                "seconds": seconds,
                "reason": _EXCLUDED_REASON.get(
                    label, f"Conta em {label}, não nesta linha."
                ),
            })
        return result


def _add_legacy_nesting(sector_nodes: list[Node], legacy: list[dict]) -> None:
    """Nestings sem horário (só duração) como um trecho por máquina, no Corte."""

    by_machine: dict[str, float] = defaultdict(float)
    for item in legacy:
        by_machine[item["resource"] or "Não informado"] += item["seconds"]
    if not by_machine:
        return
    sector = next((n for n in sector_nodes if n.label.casefold() == "corte"), None)
    if sector is None:
        sector = Node("sector", "Corte", 0.0, [])
        sector_nodes.append(sector)
    for machine, seconds in by_machine.items():
        stretch = Node(
            "stretch", _LEGACY_NESTING_LABEL, seconds, [],
            {"start": None, "end": None, "who": None, "origin": "nesting", "record_id": None},
        )
        resource = next(
            (n for n in sector.children if n.label.casefold() == machine.casefold()), None
        )
        if resource is None:
            resource = Node("resource", machine, 0.0, [])
            sector.children.append(resource)
        resource.children.append(stretch)
        resource.seconds += seconds
        sector.seconds += seconds
    sector.children.sort(key=_by_seconds)


def _belongs(metric: str, seg) -> bool:
    if metric == "tempo.a_esclarecer":
        return seg.state_conflict
    if metric == "tempo.parada_planejada":
        return (
            seg.category is EventCategory.DOWNTIME
            and seg.stop_classification is StopClassification.PLANNED
        )
    if metric == "tempo.parada_nao_planejada":
        # Como o cartão da Visão Geral: parada total menos a planejada. Parada
        # sem classificação (leitura legada) conta como não planejada.
        return (
            seg.category is EventCategory.DOWNTIME
            and seg.stop_classification is not StopClassification.PLANNED
        )
    return seg.category is _CATEGORY_BY_METRIC[metric]


def _official_total(metric: str, consolidated: dict) -> float:
    """Mesmo número que ``get_overview`` publica (``hours.*``) para a métrica."""

    if metric == "tempo.a_esclarecer":
        return float(consolidated["conflicting_state_seconds"])
    if metric in ("tempo.parada_planejada", "tempo.parada_nao_planejada"):
        by_class = consolidated["totals_by_stop_classification"].get(
            EventCategory.DOWNTIME, {}
        )
        planned = float(by_class.get(StopClassification.PLANNED, 0.0))
        if metric == "tempo.parada_planejada":
            return planned
        return float(consolidated["totals"].get(EventCategory.DOWNTIME, 0.0)) - planned
    return float(consolidated["totals"].get(_CATEGORY_BY_METRIC[metric], 0.0))


def _bucket_label(seg) -> str:
    if seg.state_conflict:
        return "Tempo a esclarecer"
    if seg.category is EventCategory.DOWNTIME:
        if seg.stop_classification is StopClassification.PLANNED:
            return "Parada planejada"
        return "Parada não planejada"
    return _CATEGORY_LABEL.get(seg.category, "Sem classificação")


def _first_state_row(seg, rows):
    """Linha de estado que sustenta o trecho; nunca uma que o contradiz.

    Só vale a linha cuja categoria física bate com a do segmento (produção que
    venceu uma parada não herda operador/motivo da parada vencida). Trecho em
    conflito não tem categoria única: usa a primeira fonte.
    """

    for ref in seg.source_refs:
        ref = str(ref)
        if not ref.startswith(_STATE_REF_PREFIX):
            continue
        row = rows.get(ref[len(_STATE_REF_PREFIX):])
        if row is None:
            continue
        if seg.state_conflict or physical_state_category(row) is seg.category:
            return row
    return None


def _motivo(seg, rows) -> str | None:
    row = _first_state_row(seg, rows)
    motivo = str((row or {}).get("motivo") or "").strip()
    return motivo or None


def _by_seconds(node: Node):
    return (-node.seconds, node.label.casefold())


def _sector_node(sector, resources, rows, multi_day) -> Node:
    resource_nodes = [
        _resource_node(resource, segs, rows, multi_day)
        for resource, segs in resources.items()
    ]
    resource_nodes.sort(key=_by_seconds)
    return Node("sector", sector, sum(n.seconds for n in resource_nodes), resource_nodes)


def _resource_node(resource, segs, rows, multi_day) -> Node:
    stretches = [_stretch_node(seg, rows, multi_day) for seg in sorted(segs, key=_by_seconds_seg)]
    return Node("resource", resource, sum(n.seconds for n in stretches), stretches)


def _by_seconds_seg(seg):
    return (-seg.seconds, seg.start)


def _stretch_node(seg, rows, multi_day) -> Node:
    row = _first_state_row(seg, rows)
    refs = [str(ref) for ref in seg.source_refs]
    first_ref = refs[0] if refs else ""
    origin = str((row or {}).get("origem") or "").strip() or (
        first_ref.split(":", 1)[0] if first_ref else ""
    )
    who = str((row or {}).get("operador") or "").strip() or None
    detail: dict[str, Any] = {
        "start": seg.start.isoformat(),
        "end": seg.end.isoformat(),
        "who": who,
        "origin": origin or None,
        # Todas as fontes que formaram o trecho, separadas por vírgula.
        "record_id": ", ".join(refs) or None,
    }
    motivo = _motivo(seg, rows)
    if motivo:
        detail["motivo"] = motivo
    if seg.rule is not None:
        detail["rule"] = _RULE_APPLIED_TEXT[seg.rule]
    return Node("stretch", _stretch_label(seg, multi_day), seg.seconds, [], detail)


def _stretch_label(seg, multi_day) -> str:
    if multi_day or seg.start.date() != seg.end.date():
        return f"{seg.start:%d/%m %H:%M} → {seg.end:%d/%m %H:%M}"
    return f"{seg.start:%H:%M} → {seg.end:%H:%M}"


def _no_calendar_notes(metric, selected, calendar_resources) -> list[str]:
    if metric in _NO_AVERAGE_METRICS:
        return []
    by_resource: dict[str, float] = defaultdict(float)
    for seg in selected:
        if seg.resource not in calendar_resources:
            by_resource[seg.resource] += seg.seconds
    if not by_resource:
        return []
    hours = sum(by_resource.values()) / 3600.0
    count = len(by_resource)
    plural = "recurso sem turno cadastrado" if count == 1 else "recursos sem turno cadastrado"
    return [
        f"{count} {plural}, {hours:.1f} h, entram no total mas não na média."
    ]


def _truncate(sector_nodes: list[Node], max_nodes: int) -> tuple[list[Node], bool]:
    """Corta a árvore em ``max_nodes`` nós sem perder segundos.

    Nível a nível (setores, recursos, trechos) mantém os maiores; o que sai vira
    um nó "outros N ..." com o total correto, então a soma dos setores continua
    fechando com o número clicado.
    """

    if _count(sector_nodes) <= max_nodes:
        return sector_nodes, False

    root = Node("root", "", 0.0, sector_nodes)
    layer = [(root, sector_nodes)]
    budget = max(1, max_nodes)
    for kind, plural in (
        ("sector", "setores"), ("resource", "recursos"), ("stretch", "trechos")
    ):
        layer, used = _fit_level(layer, budget, kind, plural)
        budget -= used
    return root.children, True


def _count(nodes: list[Node]) -> int:
    return sum(1 + _count(node.children) for node in nodes)


def _fit_level(layer, budget: int, kind: str, plural: str):
    """Distribui ``budget`` nós entre os filhos dos pais da camada.

    ``layer`` = [(pai, filhos completos)]. Escolhe os maiores filhos (ranking
    global); cada pai com filhos cortados gasta mais um nó para o "outros N".
    Retorna a próxima camada [(filho mantido, filhos completos dele)] e o total
    de nós usados.
    """

    ranked = sorted(
        ((index, child) for index, (_parent, kids) in enumerate(layer) for child in kids),
        key=lambda item: _by_seconds(item[1]),
    )

    def cost(n: int) -> int:
        kept_per_parent = defaultdict(int)
        for index, _child in ranked[:n]:
            kept_per_parent[index] += 1
        return n + sum(
            1
            for index, (_parent, kids) in enumerate(layer)
            if kids and kept_per_parent[index] < len(kids)
        )

    best = next((n for n in range(min(len(ranked), budget), -1, -1) if cost(n) <= budget), None)
    # Sem orçamento nem para o "outros N", mantém os maiores que couberem e
    # marca o pai como cortado: nunca omite filhos em silêncio.
    add_others = best is not None
    if best is None:
        best = min(len(ranked), budget)
    kept = defaultdict(list)
    for index, child in ranked[:best]:
        kept[index].append(child)

    next_layer = []
    used = 0
    for index, (parent, kids) in enumerate(layer):
        kept_kids = sorted(kept[index], key=_by_seconds)
        rest = [child for child in kids if all(child is not k for k in kept_kids)]
        # Guarda os filhos completos de cada mantido antes do próximo nível.
        next_layer.extend((child, list(child.children)) for child in kept_kids)
        parent.children = list(kept_kids)
        if rest and add_others:
            parent.children.append(
                Node(kind, f"outros {len(rest)} {plural}", sum(c.seconds for c in rest))
            )
        elif rest:
            parent.truncated = True
        used += len(parent.children)
    for child, _kids in next_layer:
        child.children = []
    return next_layer, used
