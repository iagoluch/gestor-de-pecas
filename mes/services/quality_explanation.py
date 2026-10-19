"""Explicação de valor da família ``qld.*``: Análises > Qualidade e Alertas/Auditoria.

Contrato: ``docs/superpowers/specs/2026-10-19-explicacao-valor-contrato.md``.

Sem conta própria, como em ``value_explanation``:

- ``qld.boa|refugo|retrabalho``: o número é ``IndustrialAnalyticsService.quality``
  (``totals``), o mesmo da tela Análises > Qualidade, e a árvore usa os MESMOS
  eventos que ela somou (``_quantity_events``, em cache na mesma instância).
- ``qld.auditoria.*``: o número é ``AuditService.run_period`` (``count`` e
  ``by_severity``), o mesmo dos cartões de Alertas e da Auditoria, e a árvore
  usa a MESMA lista ``issues``.

A ``reconciliation`` confere a soma das folhas contra o número da tela: se as
duas pontas divergirem um dia, a divergência aparece em vez de ficar escondida.
"""

from __future__ import annotations

from collections import defaultdict
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
    _iso,
    _Leaf,
    _reconciliation,
    _resource_node,
    _stamp_label,
    _text,
)


_NO_SECTOR = "Não informado"  # mesmo rótulo de ``quality()["by_sector"]``
_NO_RESOURCE = "Sem recurso informado"
_NO_REASON = "Não informado"  # mesmo rótulo de ``quality()["scrap_reasons"]``
_QUANTITY_KINDS = ("boa", "refugo", "retrabalho")
_QUANTITY_LABEL = {"boa": "Peças boas", "refugo": "Refugo", "retrabalho": "Retrabalho"}
_QUANTITY_EXCLUDED_REASON = {
    ("boa", "refugo"): "Peça refugada não conta como boa.",
    ("boa", "retrabalho"): "Peça em retrabalho não conta como boa de primeira passagem.",
    ("refugo", "boa"): "Peça boa não é refugo.",
    ("refugo", "retrabalho"): "Peça em retrabalho não é refugo; ela volta para ser refeita.",
    ("retrabalho", "boa"): "Peça boa não é retrabalho.",
    ("retrabalho", "refugo"): "Peça refugada não volta para retrabalho; ela é perda.",
}

# Severidades na ordem dos cartões; ``info`` existe no enum mas a auditoria não
# a coloca na lista de alertas (lacuna de calendário fica em ``diagnostics``).
_SEVERITY_ORDER = ("critico", "erro", "aviso", "info")
_SEVERITY_LABEL = {
    "critico": "Críticos",
    "erro": "Erros",
    "aviso": "Atenções",
    "info": "Informativos",
}
_SEVERITY_BY_METRIC = {
    "qld.auditoria.critico": "critico",
    "qld.auditoria.erro": "erro",
    "qld.auditoria.aviso": "aviso",
}

# Nome simples de cada conferência de ``mes/services/audit.py``.
_ISSUE_LABEL = {
    "producao_sem_quantidade_boa": "Apontamento finalizado sem peças boas",
    "op_sem_operador": "OP ativa sem operador",
    "op_sem_recurso": "OP ativa sem recurso",
    "operador_sem_recurso": "Operador em apontamento sem recurso",
    "recurso_ativo_sem_op": "Recurso ativo sem OP",
    "intervalo_invalido": "Fim antes do início",
    "sobreposicao_estados_incompativeis": "Recurso em dois estados ao mesmo tempo",
    "recurso_em_setores_conflitantes": "Recurso em dois setores ao mesmo tempo",
    "estado_fisico_desconhecido": "Estado do recurso desconhecido",
    "recurso_produzindo_sem_op": "Recurso produzindo sem OP",
    "fim_turno_sem_interrupcao_programada": "Virada de turno sem pausa automática",
    "rateio_nao_conserva_tempo_fisico": "Rateio entre OPs não fecha com o tempo da máquina",
}

_AUDIT_SOURCES = (
    "As conferências olham os apontamentos do período (o que foi lançado no "
    "posto), os estados físicos dos recursos (produzindo, parado, setup), as "
    "viradas oficiais de turno e o rateio do tempo da máquina entre OPs."
)

QUALITY_TEXT: dict[str, dict[str, Any]] = {
    "qld.boa": {
        "label": "Produção boa (Análises > Qualidade)",
        "unit": "pcs",
        "kind": "boa",
        "reason": "Peças lançadas como boas no período e nos filtros escolhidos, como soma a tela de Qualidade.",
        "rule": (
            "Soma das quantidades lançadas como boas nos lançamentos de quantidade "
            "(quantidade negativa conta como zero). Refugo e retrabalho não entram."
        ),
    },
    "qld.refugo": {
        "label": "Refugo (Análises > Qualidade)",
        "unit": "pcs",
        "kind": "refugo",
        "reason": "Peças perdidas, lançadas como refugo no período e nos filtros escolhidos.",
        "rule": (
            "Soma das quantidades lançadas como refugo nos lançamentos de quantidade "
            "(quantidade negativa conta como zero). Cada lançamento mostra o motivo, quando existe."
        ),
    },
    "qld.retrabalho": {
        "label": "Retrabalho (Análises > Qualidade)",
        "unit": "pcs",
        "kind": "retrabalho",
        "reason": "Peças que voltaram para ser refeitas, lançadas no período e nos filtros escolhidos.",
        "rule": (
            "Soma das quantidades lançadas como retrabalho nos lançamentos de quantidade "
            "(quantidade negativa conta como zero)."
        ),
    },
    "qld.auditoria.total": {
        "label": "Inconsistências (total)",
        "unit": "count",
        "severity": None,
        "empty": "Nenhuma inconsistência encontrada no período e nos filtros escolhidos.",
        "reason": (
            "Quantos registros do período têm algum dado que não fecha, somando "
            "críticos, erros e atenções."
        ),
        "rule": (
            "Conta cada inconsistência encontrada uma vez, quebrada por gravidade. "
            + _AUDIT_SOURCES
        ),
    },
    "qld.auditoria.critico": {
        "label": "Inconsistências críticas",
        "unit": "count",
        "severity": "critico",
        "empty": "Nenhuma inconsistência crítica no período e nos filtros escolhidos.",
        "reason": (
            "Registros em que o dado contradiz a própria fábrica: fim antes do "
            "início, máquina em dois estados ou dois setores ao mesmo tempo, "
            "estado da máquina desconhecido, OP ativa sem recurso, virada de turno "
            "sem pausa automática ou rateio entre OPs que não fecha."
        ),
        "rule": "Conta as inconsistências de gravidade crítica. " + _AUDIT_SOURCES,
    },
    "qld.auditoria.erro": {
        "label": "Inconsistências de erro",
        "unit": "count",
        "severity": "erro",
        "empty": "Nenhuma inconsistência de erro no período e nos filtros escolhidos.",
        "reason": (
            "Registros com uma informação faltando: apontamento finalizado sem "
            "peças boas, OP ativa sem operador, operador sem recurso, recurso "
            "ativo sem OP ou recurso produzindo sem OP."
        ),
        "rule": "Conta as inconsistências de gravidade erro. " + _AUDIT_SOURCES,
    },
    "qld.auditoria.aviso": {
        "label": "Inconsistências de atenção",
        "unit": "count",
        "severity": "aviso",
        "empty": "Nenhuma inconsistência de atenção no período e nos filtros escolhidos.",
        "reason": "Registros que merecem uma olhada, mas não impedem a conta.",
        "rule": (
            "Conta as inconsistências de gravidade atenção. Hoje nenhuma "
            "conferência da auditoria usa este nível, então o cartão fica em 0. "
            + _AUDIT_SOURCES
        ),
    },
}

_NOTE_NO_CUTTING = (
    "Esta tela soma só os lançamentos de quantidade e não inclui as peças boas "
    "do Corte (tarefas de corte concluídas), que a Visão Geral inclui. Por isso "
    "as peças boas daqui podem ser menores que as da Visão Geral."
)
_NOTE_QUALITY_FALLBACK = (
    "Não há fonte de lançamentos de quantidade disponível: a tela de Qualidade "
    "usa as quantidades dos apontamentos (fonte reserva) e esta explicação usa a "
    "mesma fonte. Sem data e sem número de lançamento."
)
_NOTE_RELIABILITY = (
    "Não existe percentual de confiabilidade dos dados: ainda não há fórmula "
    "oficial, então o sistema não inventa um."
)
_NOTE_PHYSICAL_FALLBACK = (
    "Não há estados físicos dos recursos gravados neste período; os conflitos de "
    "estado foram procurados nas linhas do tempo dos apontamentos (fonte reserva)."
)


class QualityExplanationService:
    def __init__(self, analytics, audit, now_func=None):
        self.analytics = analytics
        self.audit = audit
        self._clock = now_func

    def explain(
        self,
        metric: str,
        filters: AnalyticsFilter,
        *,
        max_leaves: int = MAX_LEAVES_PER_RESOURCE,
    ) -> ValueExplanation:
        text = QUALITY_TEXT.get(metric)
        if text is None:
            raise UnknownMetricError(f"Métrica desconhecida: {metric!r}")
        if metric.startswith("qld.auditoria."):
            return self._explain_audit(metric, text, filters, max_leaves)
        return self._explain_quantity(metric, text, filters, max_leaves)

    def _now(self) -> datetime:
        for clock in (
            self._clock,
            getattr(self.analytics, "_now", None),
            getattr(self.audit, "_now", None),
        ):
            if callable(clock):
                value = clock()
                if isinstance(value, datetime):
                    return value
        return datetime.now()

    # ------------------------------------------------------- Análises > Qualidade

    def _explain_quantity(self, metric, text, filters, max_leaves) -> ValueExplanation:
        kind = text["kind"]
        payload = self.analytics.quality(filters)
        # Mesma instância e mesma chave de cache: são os eventos que quality() somou.
        events, complete_source = self.analytics._quantity_events(filters)
        totals = {name: int((payload.get("totals") or {}).get(name) or 0) for name in _QUANTITY_KINDS}

        groups: dict[str, dict[str, dict]] = defaultdict(dict)
        unknown_qty = 0
        unknown_count = 0
        empty_count = 0
        for event in events:
            event_kind = str(event.get("tipo") or "").strip().casefold()
            qty = max(0, int(event.get("quantidade") or 0))
            if event_kind not in _QUANTITY_KINDS:
                unknown_qty += qty
                unknown_count += 1
                continue
            if event_kind != kind:
                continue
            if qty == 0:
                empty_count += 1
                continue
            # Mesmo rótulo de setor que ``quality()["by_sector"]`` usa.
            sector = str(event.get("tipo_setor") or _NO_SECTOR)
            resource = _text(event.get("recurso")) or _NO_RESOURCE
            stamp = _iso(event.get("data_hora"))
            op = _text(event.get("op"))
            bucket = groups[sector].setdefault(resource.casefold(), {"name": resource, "leaves": []})
            bucket["leaves"].append(_Leaf(
                "event",
                _stamp_label(f"OP {op}" if op else "Sem OP", stamp),
                float(qty),
                stamp,
                _detail(
                    id=event.get("id"),
                    op=op,
                    operacao=_text(event.get("numero_operacao")),
                    produto=_text(event.get("produto_codigo")),
                    operador=_text(event.get("operador")),
                    data_hora=stamp,
                    motivo=_text(event.get("motivo")),
                    causa_raiz=_text(event.get("causa_raiz")),
                    origem=_text(event.get("origem")),
                ),
            ))

        children = _group_nodes(groups, "sector", max_leaves)
        value = float(totals[kind])
        reconciliation = _reconciliation(value, sum(node.value or 0.0 for node in children))
        reason = (
            text["reason"]
            if children
            else f"Nenhum lançamento de {_QUANTITY_LABEL[kind].lower()} no período e nos filtros escolhidos."
        )

        excluded = [
            {
                "label": _QUANTITY_LABEL[other],
                "value": float(totals[other]),
                "reason": _QUANTITY_EXCLUDED_REASON[(kind, other)],
            }
            for other in _QUANTITY_KINDS
            if other != kind and totals[other]
        ]
        if unknown_count:
            excluded.append({
                "label": f"Lançamentos de tipo desconhecido ({unknown_count})",
                "value": float(unknown_qty),
                "reason": "O tipo não é boa, refugo nem retrabalho; a tela de Qualidade também não soma.",
            })
        if empty_count:
            excluded.append({
                "label": f"Lançamentos com quantidade zero ou negativa ({empty_count})",
                "value": 0.0,
                "reason": "A tela de Qualidade conta estes lançamentos como 0 peça.",
            })

        notes: list[str] = []
        if kind == "boa":
            notes.append(_NOTE_NO_CUTTING)
            overview_good = self._overview_good(filters)
            if overview_good is not None and overview_good != totals["boa"]:
                notes.append(
                    f"Neste período a Visão Geral mostra {overview_good} peças boas e "
                    f"esta tela mostra {totals['boa']}."
                )
        elif kind in ("refugo", "retrabalho"):
            ranking = payload.get("scrap_reasons" if kind == "refugo" else "rework_reasons") or []
            if ranking:
                parts = "; ".join(
                    f"{item.get('motivo') or _NO_REASON}: {_pieces(item.get('quantidade'))}"
                    for item in ranking
                )
                notes.append(f"Por motivo: {parts}.")
        if kind == "retrabalho" and payload.get("reason"):
            notes.append(str(payload["reason"]))
        if not complete_source:
            notes.append(_NOTE_QUALITY_FALLBACK)

        return self._result(metric, text, value, reason, children, excluded, reconciliation, notes)

    def _overview_good(self, filters) -> int | None:
        management = getattr(self.analytics, "management", None)
        if management is None:
            return None
        production = (management.get_overview(filters) or {}).get("production") or {}
        raw = production.get("good")
        return int(raw) if raw is not None else None

    # ------------------------------------------------------- Alertas / Auditoria

    def _explain_audit(self, metric, text, filters, max_leaves) -> ValueExplanation:
        payload = self.audit.run_period(filters)
        issues = list(payload.get("issues") or [])
        by_severity = payload.get("by_severity") or {}
        known = set(_SEVERITY_ORDER)
        unknown = [issue for issue in issues if _severity(issue) not in known]
        severity = text["severity"]

        if severity is None:
            value = float(payload.get("count", len(issues)) or 0)
            children = []
            for level in _SEVERITY_ORDER:
                chosen = [issue for issue in issues if _severity(issue) == level]
                if chosen:
                    children.append(_severity_node(_SEVERITY_LABEL[level], chosen, max_leaves))
            unknown_levels = sorted({_severity(issue) for issue in unknown})
            for level in unknown_levels:
                chosen = [issue for issue in unknown if _severity(issue) == level]
                label = f"Gravidade não reconhecida: {level or 'vazia'}"
                children.append(_severity_node(label, chosen, max_leaves))
            excluded: list[dict] = []
        else:
            value = float(by_severity.get(severity) or 0)
            chosen = [issue for issue in issues if _severity(issue) == severity]
            children = _type_nodes(chosen, max_leaves)
            excluded = [
                {
                    "label": _SEVERITY_LABEL[level],
                    "value": float(by_severity.get(level) or 0),
                    "reason": f"Gravidade diferente; conta no cartão {_SEVERITY_LABEL[level]}.",
                }
                for level in _SEVERITY_ORDER
                if level != severity and by_severity.get(level)
            ]
            if unknown:
                excluded.append({
                    "label": "Gravidade não reconhecida",
                    "value": float(len(unknown)),
                    "reason": (
                        "A gravidade não é crítica, erro, atenção nem informativa; "
                        "estes registros só entram no Total."
                    ),
                })

        reconciliation = _reconciliation(value, sum(node.value or 0.0 for node in children))
        reason = (
            text["reason"]
            if children
            else text["empty"]
        )

        notes = [_NOTE_RELIABILITY]
        gaps = int((payload.get("diagnostics") or {}).get("calendar_gap_count") or 0)
        notes.append(
            "Lacunas de calendário (recurso parado no turno sem nenhum registro) não "
            "entram aqui: são diagnóstico, não alerta, e já aparecem como parada "
            "\"Sem apontamento\" nas métricas."
            + (f" Neste período foram {gaps}." if gaps else "")
        )
        if filters.op or filters.operacao is not None:
            notes.append(
                "Com filtro de OP ou de operação, a conferência do rateio do tempo "
                "entre OPs não roda; tire esse filtro para vê-la."
            )
        else:
            notes.append(
                "A conferência do rateio do tempo entre OPs só roda sem filtro de OP "
                "ou de operação (como agora)."
            )
        if payload.get("physical_state_source") == "timeline_apontamentos_fallback":
            notes.append(_NOTE_PHYSICAL_FALLBACK)
        total = len(issues)
        notes.append(
            "A tabela da tela Auditoria mostra só as primeiras 200 linhas; os cartões "
            "e esta explicação contam todas"
            + (f" ({total} no total)." if total > 200 else ".")
        )
        if unknown:
            notes.append(
                f"{len(unknown)} registro(s) com gravidade não reconhecida: entram no "
                "Total, mas em nenhum dos cartões Críticos, Erros ou Atenções."
            )

        return self._result(metric, text, value, reason, children, excluded, reconciliation, notes)

    # ------------------------------------------------------------------ comum

    def _result(self, metric, text, value, reason, children, excluded, reconciliation, notes):
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


def _pieces(value: Any) -> str:
    qty = int(value or 0)
    return f"{qty} peça" if qty == 1 else f"{qty} peças"


def _severity(issue: dict) -> str:
    return str(issue.get("severity") or "").strip()


def _issue_label(kind: str) -> str:
    if kind in _ISSUE_LABEL:
        return _ISSUE_LABEL[kind]
    return kind.replace("_", " ").strip().capitalize() or "Tipo não informado"


def _issue_leaf(issue: dict) -> _Leaf:
    start = _iso(issue.get("start"))
    op = _text(issue.get("op"))
    return _Leaf(
        "event",
        _stamp_label(f"OP {op}" if op else "Sem OP", start),
        1.0,
        start,
        _detail(
            mensagem=_text(issue.get("message")),
            severidade=_severity(issue),
            apontamento=issue.get("appointment_id"),
            op=op,
            operacao=_text(issue.get("operation")),
            setor=_text(issue.get("sector")),
            inicio=start,
            fim=_iso(issue.get("end")),
            segundos=issue.get("seconds"),
            segundos_fisicos=issue.get("physical_seconds"),
            segundos_atribuidos=issue.get("attributed_seconds"),
            fonte=_text(issue.get("source")),
        ),
    )


def _type_nodes(issues: list[dict], max_leaves: int) -> list[ValueNode]:
    """Tipo da inconsistência -> recurso -> registro."""

    groups: dict[str, dict[str, dict]] = defaultdict(dict)
    for issue in issues:
        label = _issue_label(_text(issue.get("type")))
        resource = _text(issue.get("resource")) or _NO_RESOURCE
        bucket = groups[label].setdefault(resource.casefold(), {"name": resource, "leaves": []})
        bucket["leaves"].append(_issue_leaf(issue))
    return _group_nodes(groups, "group", max_leaves)


def _severity_node(label: str, issues: list[dict], max_leaves: int) -> ValueNode:
    children = _type_nodes(issues, max_leaves)
    return ValueNode(
        kind="group",
        label=label,
        value=sum(node.value or 0.0 for node in children),
        children=children,
    )


def _group_nodes(groups: dict[str, dict[str, dict]], kind: str, max_leaves: int) -> list[ValueNode]:
    nodes = []
    for label, resources in groups.items():
        children = [
            _resource_node(bucket["name"], bucket["leaves"], max_leaves)
            for bucket in resources.values()
        ]
        children.sort(key=lambda node: (-(node.value or 0.0), node.label.casefold()))
        nodes.append(ValueNode(
            kind=kind,
            label=label,
            value=sum(node.value or 0.0 for node in children),
            children=children,
        ))
    nodes.sort(key=lambda node: (-(node.value or 0.0), node.label.casefold()))
    return nodes
