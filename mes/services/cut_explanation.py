"""Explicação de valor da família ``cut.*``: tempos dos nestings do Corte.

Fonte única: ``ManagementService.get_nesting_times`` — a mesma de
Rastreabilidade > Lote / Material / Nesting (``/traceability/nestings``).
Nenhuma conta nova: o serviço só soma as mesmas linhas que a tela soma.

Vocabulário do Corte: *plano* = a chapa com as OPs; *nesting* = cada repetição
do plano. A árvore é Máquina > Tarefa > Plano > Nesting.

Ids: ``cut.nestings`` (quantidade), ``cut.previsto`` e ``cut.realizado``
(horas) e ``cut.desvio`` (%). O "realizado" é o tempo TOTAL do nesting, igual ao
cartão; o tempo dentro do período aparece à parte, no detalhe de cada nesting.
O Corte não tem tempo padrão (norma de tempo): por isso não entra na
Performance dos outros setores.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from mes.contracts import AnalyticsFilter
from mes.services.metric_explanation import UnknownMetricError
from mes.services.value_explanation import (
    MAX_LEAVES_PER_RESOURCE,
    ValueExplanation,
    ValueNode,
    _any_truncated,
    _detail,
    _reconciliation,
)


_NO_MACHINE = "Máquina não informada"
_NO_TASK = "Tarefa não informada"
_NO_PLAN = "Plano sem programa"

CUT_TEXT: dict[str, dict[str, str]] = {
    "cut.nestings": {
        "label": "Nestings no filtro",
        "unit": "count",
        "rule": "Cada nesting executado (início de corte) que cruza o período e a máquina filtrados conta 1.",
    },
    "cut.previsto": {
        "label": "Tempo previsto do Corte",
        "unit": "hours",
        "rule": "Soma do tempo previsto de cada nesting (vem do plano do SigmaNEST). Nesting sem previsto soma 0.",
    },
    "cut.realizado": {
        "label": "Tempo realizado do Corte",
        "unit": "hours",
        "rule": (
            "Soma do tempo TOTAL de cada nesting, do início ao fim (ou até agora, se ainda está cortando). "
            "É o tempo físico inteiro do nesting, mesmo a parte fora do período."
        ),
    },
    "cut.desvio": {
        "label": "Desvio do previsto",
        "unit": "pct",
        "rule": "(Tempo realizado − Tempo previsto) ÷ Tempo previsto × 100, sobre as somas de todos os nestings do filtro.",
    },
}


def _seconds(row: dict, key: str) -> float:
    value = row.get(key)
    return float(value) if value is not None else 0.0


def _hours(seconds: float) -> float:
    return seconds / 3600.0


def _text(value: Any, fallback: str) -> str:
    text = str(value).strip() if value is not None else ""
    return text or fallback


def _node(kind: str, label: str, children: list[ValueNode]) -> ValueNode:
    return ValueNode(
        kind=kind,
        label=label,
        value=sum(child.value or 0.0 for child in children),
        children=children,
        truncated=any(child.truncated for child in children),
    )


class CutExplanationService:
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
        text = CUT_TEXT.get(metric)
        if text is None:
            raise UnknownMetricError(f"Métrica desconhecida: {metric!r}")

        rows = [dict(row) for row in (self.management.get_nesting_times(filters) or [])]

        previsto = sum(_seconds(row, "previsto_segundos") for row in rows)
        real = sum(_seconds(row, "real_segundos") for row in rows)
        notes = self._notes(filters)
        excluded: list[dict] = []

        if metric == "cut.desvio":
            return self._explain_desvio(text, previsto, real, len(rows), notes)

        if metric == "cut.nestings":
            measure, total, reason = self._count_measure(len(rows))
        elif metric == "cut.previsto":
            semprevisto = sum(1 for row in rows if not _seconds(row, "previsto_segundos"))
            if semprevisto:
                excluded.append({
                    "label": "Nestings sem tempo previsto",
                    "value": str(semprevisto),  # texto: a tela formata "value" na unidade da métrica (horas)
                    "reason": "Entram na contagem de nestings, mas somam 0 de previsto.",
                })
            measure = lambda row: _hours(_seconds(row, "previsto_segundos"))  # noqa: E731
            total = _hours(previsto)
            reason = f"{len(rows)} nestings somam {_hours(previsto):.2f} h de tempo previsto."
        else:
            measure = lambda row: _hours(_seconds(row, "real_segundos"))  # noqa: E731
            total = _hours(real)
            reason = f"{len(rows)} nestings somam {_hours(real):.2f} h de tempo realizado (tempo total de cada nesting)."
            notes.append(
                "O realizado é o tempo TOTAL do nesting. Nesting que começou antes do período "
                "ou ainda corta conta inteiro; a parte dentro do período aparece em cada nesting."
            )

        children = self._tree(rows, measure, max_leaves)
        value = float(total)
        return ValueExplanation(
            metric=metric,
            label=text["label"],
            unit=text["unit"],
            value=value,
            reason=reason,
            rule=text["rule"],
            children=children,
            excluded=excluded,
            reconciliation=_reconciliation(value, sum(child.value or 0.0 for child in children)),
            calculated_at=self._now().isoformat(),
            truncated=_any_truncated(children),
            notes=notes,
        )

    # ------------------------------------------------------------------ partes

    @staticmethod
    def _count_measure(count: int):
        return (lambda row: 1.0), float(count), f"{count} nestings executados no filtro."

    def _explain_desvio(self, text, previsto, real, count, notes) -> ValueExplanation:
        has_planned = previsto > 0
        value = (real - previsto) / previsto * 100.0 if has_planned else None
        children = [
            ValueNode(kind="input", label="Tempo realizado", value=real, detail={"unidade": "segundos"}),
            ValueNode(kind="input", label="Tempo previsto", value=previsto, detail={"unidade": "segundos"}),
        ]
        if has_planned:
            reason = (
                f"Realizado {_hours(real):.2f} h contra previsto {_hours(previsto):.2f} h "
                f"em {count} nestings."
            )
            reconciliation = _reconciliation(value, (children[0].value - children[1].value) / children[1].value * 100.0)
        else:
            reason = "Sem tempo previsto no filtro: não há contra o que comparar, então o desvio não existe."
            reconciliation = {"ok": True, "sum": None, "diff": None}
        notes.append("As listas de nestings por trás de cada soma estão em “Tempo previsto” e “Tempo realizado”.")
        return ValueExplanation(
            metric="cut.desvio",
            label=text["label"],
            unit=text["unit"],
            value=value,
            reason=reason,
            rule=text["rule"],
            children=children if has_planned else [],
            excluded=[],
            reconciliation=reconciliation,
            calculated_at=self._now().isoformat(),
            truncated=False,
            notes=notes,
        )

    def _tree(self, rows: list[dict], measure, max_leaves: int) -> list[ValueNode]:
        machines: dict[str, dict[str, dict[str, list[dict]]]] = {}
        for row in rows:
            machine = _text(row.get("maquina"), _NO_MACHINE)
            task = _text(row.get("tarefa"), _NO_TASK)
            plan = _text(row.get("plano_hash") or row.get("programa"), _NO_PLAN)
            machines.setdefault(machine, {}).setdefault(task, {}).setdefault(plan, []).append(row)

        nodes = []
        for machine, tasks in machines.items():
            leaves_budget = max_leaves
            task_nodes = []
            for task, plans in tasks.items():
                plan_nodes = []
                for plan_rows in plans.values():
                    plan_rows.sort(key=lambda r: str(r.get("inicio") or ""), reverse=True)
                    kept, rest = plan_rows[:max(leaves_budget, 0)], plan_rows[max(leaves_budget, 0):]
                    leaves_budget -= len(kept)
                    leaves = [self._leaf(row, measure) for row in kept]
                    if rest:
                        leaves.append(ValueNode(
                            kind="event",
                            label=f"Outros {len(rest)} nestings" if len(rest) > 1 else "Outro nesting",
                            value=sum(measure(row) for row in rest),
                            truncated=True,
                        ))
                    first = plan_rows[0]
                    plan_label = f"Plano {_text(first.get('programa'), _NO_PLAN)}"
                    plan_nodes.append(_node("part", plan_label, leaves))
                plan_nodes.sort(key=lambda n: -(n.value or 0.0))
                task_nodes.append(_node("part", f"Tarefa {task}", plan_nodes))
            task_nodes.sort(key=lambda n: -(n.value or 0.0))
            nodes.append(_node("resource", machine, task_nodes))
        nodes.sort(key=lambda n: -(n.value or 0.0))
        return nodes

    @staticmethod
    def _leaf(row: dict, measure) -> ValueNode:
        nesting = row.get("nesting")
        return ValueNode(
            kind="event",
            label=f"Nesting {nesting}" if nesting not in (None, "") else "Nesting",
            value=measure(row),
            detail=_detail(
                material=row.get("material"),
                espessura=row.get("espessura"),
                status=row.get("status"),
                previsto=_clock(row.get("previsto_segundos")),
                realizado_total=_clock(row.get("real_segundos")),
                realizado_no_periodo=_clock(row.get("real_periodo_segundos")),
                operador=row.get("operador_inicio") or row.get("operador_fim"),
                inicio=_stamp(row.get("inicio")),
                fim=_stamp(row.get("fim")),
            ),
        )

    @staticmethod
    def _notes(filters: AnalyticsFilter) -> list[str]:
        notes = []
        setor = (getattr(filters, "setor", None) or "").strip()
        unsupported = [
            name for name in ("op", "operacao", "produto", "turno", "operador")
            if getattr(filters, name, None)
        ]
        if (setor and setor.casefold() != "corte") or unsupported:
            notes.append(
                "O filtro atual (setor diferente de Corte, OP, operação, produto, turno ou operador) "
                "não se aplica a nestings: a lista fica vazia."
            )
        notes.append("O Corte não tem tempo padrão cadastrado; por isso não entra na Performance dos outros setores.")
        return notes

    def _now(self) -> datetime:
        for clock in (self._clock, getattr(self.management, "_now", None)):
            if callable(clock):
                moment = clock()
                if isinstance(moment, datetime):
                    return moment
        return datetime.now()


def _stamp(value: Any) -> str | None:
    if value is None:
        return None
    return value.isoformat(timespec="minutes") if hasattr(value, "isoformat") else str(value)


def _clock(seconds: Any) -> str | None:
    """Duração legível (``2h 05m``) para o detalhe; o número do nó segue em horas."""

    if seconds is None:
        return None
    total = int(round(float(seconds)))
    hours, rest = divmod(abs(total), 3600)
    return f"{hours}h {rest // 60:02d}m"
