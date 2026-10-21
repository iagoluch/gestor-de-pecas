"""Explicação de valor da família ``std.*``: tempo padrão.

S1–S5 (``std.protheus``, ``std.manual``, ``std.estimado``, ``std.fonte``,
``std.recalculo``) explicam a linha de tela de Produção > Tempo padrão; a chave
(produto, operação, recurso) vem dos filtros ``produto``/``operacao``/``recurso``.
S6 (``std.comparacoes``, ``std.padrao_acumulado``, ``std.real_acumulado``,
``std.desvio``) explica os cartões de Análises > Padrão x real e repete a conta
da própria página: só soma a linha que tem esperado E real.

Fontes únicas (nenhuma conta nova): ``listar_tempos_padrao`` e o histórico manual
do repositório, o último evento de recálculo (``ESTIMATE_EVENT_TYPE``) e
``IndustrialAnalyticsService.standard_vs_actual`` / ``standard_time_samples``.
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, time, timedelta
from typing import Any

from mes.contracts import AnalyticsFilter
from mes.domain.standard_time import (
    DEFAULT_LOOKBACK_DAYS,
    DEFAULT_MIN_SAMPLES,
    DEFAULT_PERCENTILE,
    SECTOR_WITHOUT_STANDARD_TIME,
    drop_outliers,
    estimate_standard_seconds,
    normalize_key,
)
from mes.services.metric_explanation import UnknownMetricError
from mes.services.standard_time import CHUNK_DAYS, ESTIMATE_EVENT_TYPE
from mes.services.value_explanation import (
    MAX_LEAVES_PER_RESOURCE,
    ValueExplanation,
    ValueNode,
    _any_truncated,
    _detail,
    _reconciliation,
)


_NO_KEY = "Informe produto, operação e recurso para ver a conta deste tempo."
_NO_RESOURCE = "Sem recurso informado"
_SOURCE_LABELS = {"protheus": "Protheus", "manual": "Manual", "estimado": "Estimado"}
_LINES_LIMIT = 500  # LIMITE_MAXIMO de ``listar_tempos_padrao``

STD_TEXT: dict[str, dict[str, str]] = {
    "std.protheus": {
        "label": "Tempo padrão do Protheus",
        "unit": "seconds",
        "rule": (
            "Tempo oficial por peça cadastrado no Protheus para o produto, a operação e o recurso. "
            "Não é editável aqui: um tempo manual por cima dele é recusado (erro 409)."
        ),
    },
    "std.manual": {
        "label": "Tempo padrão manual",
        "unit": "seconds",
        "rule": (
            "Tempo por peça digitado pela engenharia de manufatura. Vale a partir da data de vigência "
            "e cada mudança fica no histórico (quem, quando, valor anterior). O Corte não aceita manual."
        ),
    },
    "std.estimado": {
        "label": "Tempo padrão estimado",
        "unit": "seconds",
        "rule": (
            "P25 (o quarto mais rápido) dos segundos por peça das execuções finalizadas, depois de "
            "descartar as fora do padrão (IQR × 1,5). Só vira estimativa com a amostra mínima."
        ),
    },
    "std.fonte": {
        "label": "Fonte do tempo padrão em uso",
        "unit": "text",
        "rule": "Prioridade: Protheus > manual > estimado > sem padrão. A primeira fonte que existe é a que vale.",
    },
    "std.recalculo": {
        "label": "Chaves com tempo estimado no último recálculo",
        "unit": "count",
        "rule": (
            "Cada chave (produto, operação, recurso) com execuções elegíveis é avaliada; só ganha "
            "tempo estimado quem atinge a amostra mínima depois de descartar as fora do padrão."
        ),
    },
    "std.comparacoes": {
        "label": "Comparações do período",
        "unit": "count",
        "rule": "Cada apontamento finalizado do período é uma comparação; só as que têm tempo padrão E tempo real entram nos acumulados.",
    },
    "std.padrao_acumulado": {
        "label": "Tempo padrão acumulado",
        "unit": "hours",
        "rule": "Soma do tempo padrão oficial (Protheus ou manual) × peças boas de cada apontamento que também tem tempo real.",
    },
    "std.real_acumulado": {
        "label": "Tempo real acumulado",
        "unit": "hours",
        "rule": "Soma do tempo real de produção de cada apontamento que também tem tempo padrão.",
    },
    "std.desvio": {
        "label": "Desvio do padrão",
        "unit": "pct",
        "rule": "(Tempo real − Tempo padrão) ÷ Tempo padrão × 100, sobre os acumulados dos apontamentos comparáveis.",
    },
}

_LINE_METRICS = ("std.protheus", "std.manual", "std.estimado", "std.fonte")


def _fmt_s(seconds: Any) -> str:
    return f"{float(seconds):.2f} s".replace(".", ",")


def _stamp(value: Any) -> str | None:
    if value is None or value == "":
        return None
    return value.isoformat(timespec="minutes") if hasattr(value, "isoformat") else str(value)


def _parse_dt(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
    return None


def _num(value: Any) -> float | None:
    return float(value) if value is not None else None


class StandardTimeExplanationService:
    def __init__(self, db, analytics, now_func=None):
        self.db = db
        self.analytics = analytics
        self._clock = now_func

    def explain(
        self,
        metric: str,
        filters: AnalyticsFilter,
        *,
        max_leaves: int = MAX_LEAVES_PER_RESOURCE,
    ) -> ValueExplanation:
        text = STD_TEXT.get(metric)
        if text is None:
            raise UnknownMetricError(f"Métrica desconhecida: {metric!r}")
        if metric in _LINE_METRICS:
            return self._explain_line(metric, text, filters, max_leaves)
        if metric == "std.recalculo":
            return self._explain_recalculo(text)
        return self._explain_comparison(metric, text, filters, max_leaves)

    # ------------------------------------------------------------ S1–S4: linha

    def _explain_line(self, metric, text, filters, max_leaves) -> ValueExplanation:
        produto = (getattr(filters, "produto", None) or "").strip()
        operacao = (getattr(filters, "operacao", None) or "").strip()
        recurso = (getattr(filters, "recurso", None) or "").strip()
        if not (produto and operacao and recurso):
            return self._build(metric, text, None, _NO_KEY, [], [], [])
        key = normalize_key(produto, operacao, recurso)
        row = self._find_line(produto, recurso, key)
        if row is None:
            return self._build(
                metric, text, None,
                "Esta combinação de produto, operação e recurso não está no cadastro de tempo padrão.",
                [], [], [],
            )
        handler = {
            "std.protheus": self._protheus,
            "std.manual": self._manual,
            "std.estimado": self._estimado,
            "std.fonte": self._fonte,
        }[metric]
        return handler(metric, text, row, key, max_leaves)

    def _find_line(self, produto: str, recurso: str, key: tuple[str, str, str]) -> dict | None:
        page = self.db.listar_tempos_padrao(
            produto=produto, recurso=recurso, somente_sem_padrao=False, limite=_LINES_LIMIT,
        )
        for item in page.get("items") or []:
            candidate = normalize_key(item.get("produto_codigo"), item.get("numero_operacao"), item.get("codigo_recurso"))
            if candidate == key:
                return dict(item)
        return None

    def _protheus(self, metric, text, row, key, max_leaves) -> ValueExplanation:
        value = _num(row.get("tempo_protheus_segundos"))
        covered, total = row.get("linhas_com_protheus"), row.get("linhas_total")
        if value is None:
            reason = "O Protheus não tem tempo para esta combinação de produto, operação e recurso."
        else:
            reason = f"O Protheus cadastra {_fmt_s(value)} por peça para esta operação neste recurso."
        if covered is not None and total:
            reason += f" Há tempo em {covered} de {total} linha(s) de roteiro."
        excluded = []
        manual = _num(row.get("tempo_manual_segundos"))
        if value is not None and manual is not None:
            excluded.append({
                "label": "Tempo manual cadastrado",
                "value": _fmt_s(manual),
                "reason": "Fica por baixo do Protheus: o oficial vale e um manual por cima é recusado (409).",
            })
        return self._build(metric, text, value, reason, [], excluded, [])

    def _manual(self, metric, text, row, key, max_leaves) -> ValueExplanation:
        value = _num(row.get("tempo_manual_segundos"))
        sector = str(row.get("tipo_setor") or "").strip().casefold()
        notes: list[str] = []
        if sector == SECTOR_WITHOUT_STANDARD_TIME:
            notes.append("O Corte não aceita tempo padrão manual.")
        if value is None:
            reason = "Não há tempo manual cadastrado para esta combinação."
        else:
            reason = f"A engenharia cadastrou {_fmt_s(value)} por peça"
            who, when, since = row.get("manual_alterado_por"), _stamp(row.get("manual_alterado_em")), _stamp(row.get("manual_vigente_desde"))
            reason += f", por {who}" if who else ""
            reason += f" em {when}" if when else ""
            reason += f", vigente desde {since}." if since else "."
        history = self.db.listar_historico_tempo_padrao_manual(*key, limite=50) if value is not None or row.get("manual_alterado_em") else []
        children = [
            ValueNode(
                kind="event",
                label=f"{item.get('acao') or 'Alteração'} em {_stamp(item.get('registrado_em')) or 'data não informada'}",
                value=_num(item.get("segundos_novo")),
                detail=_detail(
                    acao=item.get("acao"),
                    por=item.get("usuario_nome"),
                    anterior=_fmt_s(item["segundos_anterior"]) if item.get("segundos_anterior") is not None else None,
                    vigente_desde=_stamp(item.get("vigente_desde")),
                    observacao=item.get("observacao"),
                ),
            )
            for item in history
        ]
        if children:
            notes.append("A lista é o histórico de alterações, da mais recente para a mais antiga; o valor de cada linha é o tempo gravado naquela alteração.")
        return self._build(metric, text, value, reason, children, [], notes)

    def _estimado(self, metric, text, row, key, max_leaves) -> ValueExplanation:
        value = _num(row.get("tempo_estimado_segundos"))
        if value is None:
            return self._build(
                metric, text, None,
                "Não há tempo estimado: faltam execuções suficientes ou ainda não houve recálculo.", [], [], [],
            )
        run = self._last_run()
        run_at = _parse_dt((run or {}).get("calculado_em")) or _parse_dt(row.get("estimado_calculado_em"))
        min_samples = int((run or {}).get("amostra_minima") or DEFAULT_MIN_SAMPLES)
        samples = self._rebuild_samples(row, key, run, run_at)
        raw = [s["segundos_por_peca"] for s in samples if s.get("segundos_por_peca") and s["segundos_por_peca"] > 0]
        kept = drop_outliers(raw)
        dropped = Counter(round(v, 9) for v in raw)
        dropped.subtract(Counter(round(v, 9) for v in kept))
        dropped_values = sorted(v for v, n in dropped.items() for _ in range(max(n, 0)))
        estimate = estimate_standard_seconds(raw, min_samples=min_samples, pct=DEFAULT_PERCENTILE)
        by_value: dict[float, list[dict]] = {}
        for sample in samples:
            by_value.setdefault(round(sample["segundos_por_peca"], 9), []).append(sample)
        leaves, rest = [], 0
        for number in sorted(kept):
            if len(leaves) >= max_leaves:
                rest += 1
                continue
            sample = (by_value.get(round(number, 9)) or [{}]).pop(0)
            leaves.append(ValueNode(
                kind="input",
                label=f"Execução {sample.get('apontamento_id')}" if sample.get("apontamento_id") is not None else "Execução",
                value=number,
                detail=_detail(inicio=_stamp(sample.get("inicio")), fim=_stamp(sample.get("fim"))),
            ))
        if rest:
            leaves.append(ValueNode(
                kind="input", label=f"Outras {rest} execuções" if rest > 1 else "Outra execução",
                value=None, truncated=True,
            ))
        excluded = [
            {"label": "Execução descartada (fora do padrão)", "value": _fmt_s(v),
             "reason": "Fora de [Q1 − 1,5 × IQR, Q3 + 1,5 × IQR]: não entra no P25."}
            for v in dropped_values[:max_leaves]
        ]
        if len(dropped_values) > max_leaves:
            excluded.append({"label": "Outras execuções descartadas", "value": str(len(dropped_values) - max_leaves), "reason": "Também fora do padrão."})
        # o recálculo grava round(p25, 3) (standard_time.py): comparar com o mesmo arredondamento
        recalculated = round(estimate.segundos_por_peca, 3) if estimate else None
        reason = (
            f"P25 de {len(kept)} execuções = {_fmt_s(value)} por peça "
            f"(amostra mínima {min_samples}, {len(dropped_values)} descartada(s) por estar(em) fora do padrão)."
        )
        notes = ["As execuções são relidas do histórico no recálculo gravado; se algum apontamento foi corrigido depois, a conferência abaixo mostra a diferença."]
        if recalculated is None:
            notes.append("Hoje as execuções da janela não bastam para refazer a conta.")
        return self._build(
            metric, text, value, reason, leaves, excluded, notes,
            reconciliation=(
                _reconciliation(value, recalculated) if recalculated is not None
                else {"ok": False, "sum": None, "diff": None}
            ),
        )

    def _fonte(self, metric, text, row, key, max_leaves) -> ValueExplanation:
        source = row.get("fonte_efetiva")
        label = _SOURCE_LABELS.get(str(source or ""), "Sem padrão")
        values = {
            "Protheus": row.get("tempo_protheus_segundos"),
            "Manual": row.get("tempo_manual_segundos"),
            "Estimado": row.get("tempo_estimado_segundos"),
        }
        children = [
            ValueNode(
                kind="part",
                label=name,
                value=_fmt_s(number) if number is not None else "Não cadastrado",
                detail=_detail(em_uso="sim" if name == label else None),
            )
            for name, number in values.items()
        ]
        reason = f"Fonte em uso: {label}." if source else "Nenhuma fonte tem tempo para esta combinação: fica sem padrão."
        return self._build(metric, text, label, reason, children, [], [])

    # --------------------------------------------------------------- S5: resumo

    def _explain_recalculo(self, text) -> ValueExplanation:
        run = self._last_run()
        if run is None:
            return self._build("std.recalculo", text, None, "Nenhum recálculo do tempo estimado foi registrado ainda.", [], [], [])
        evaluated = int(run.get("chaves_avaliadas") or 0)
        estimated = int(run.get("chaves_estimadas") or 0)
        eligible = int(run.get("execucoes_elegiveis") or 0)
        children = [
            ValueNode(kind="input", label="Execuções elegíveis", value=float(eligible)),
            ValueNode(kind="input", label="Chaves avaliadas", value=float(evaluated)),
            ValueNode(kind="input", label="Chaves com tempo estimado", value=float(estimated)),
        ]
        excluded = []
        if evaluated > estimated:
            excluded.append({
                "label": "Chaves sem amostra suficiente",
                "value": str(evaluated - estimated),
                "reason": f"Não atingiram a amostra mínima de {run.get('amostra_minima') or DEFAULT_MIN_SAMPLES} depois de descartar as fora do padrão.",
            })
        when = _stamp(run.get("calculado_em"))
        window = f"{_stamp(run.get('janela_inicio'))} a {_stamp(run.get('janela_fim'))}" if run.get("janela_inicio") else None
        reason = f"Último recálculo{f' em {when}' if when else ''}: {estimated} de {evaluated} chaves ficaram com tempo estimado, a partir de {eligible} execuções elegíveis."
        notes = [f"Janela lida: {window}."] if window else []
        return self._build(
            "std.recalculo", text, float(estimated), reason, children, excluded, notes,
            reconciliation={"ok": estimated <= evaluated, "sum": None, "diff": None},
        )

    def _last_run(self) -> dict | None:
        event = self.db.ultimo_evento_sistema(tipos=[ESTIMATE_EVENT_TYPE])
        if not event:
            return None
        details = event.get("detalhes")
        if isinstance(details, str):
            try:
                details = json.loads(details)
            except ValueError:
                details = None
        # Eventos antigos não guardavam o JSON: só o instante do recálculo é conhecido.
        run = dict(details) if isinstance(details, dict) else {}
        run.setdefault("calculado_em", event.get("data_hora"))
        return run

    def _rebuild_samples(self, row, key, run, run_at) -> list[dict]:
        """Execuções do P25: refaz a leitura por janelas de 14 dias, como ``_recalculate``.

        ponytail: relê só as janelas que cruzam o intervalo gravado da chave; no pior
        caso são 13 leituras de 14 dias. Gravar as execuções no recálculo evitaria isso.
        """
        start, end = _parse_dt(row.get("estimado_janela_inicio")), _parse_dt(row.get("estimado_janela_fim"))
        if start is None or end is None:
            return []
        window_start = _parse_dt((run or {}).get("janela_inicio"))
        window_end = _parse_dt((run or {}).get("janela_fim"))
        if window_end is None:
            window_end = datetime.combine((run_at or self._now()).date(), time.min)
        if window_start is None:
            window_start = window_end - timedelta(days=DEFAULT_LOOKBACK_DAYS)
        samples: list[dict] = []
        chunk_start = window_start
        while chunk_start < window_end:
            chunk_end = min(chunk_start + timedelta(days=CHUNK_DAYS), window_end)
            if chunk_start <= end and chunk_end >= start:
                for sample in self.analytics.standard_time_samples(AnalyticsFilter(inicio=chunk_start, fim=chunk_end)):
                    if normalize_key(sample.get("produto"), sample.get("operacao"), sample.get("recurso")) == key:
                        samples.append(sample)
            chunk_start = chunk_end
        return samples

    # --------------------------------------------------- S6: padrão x real

    def _explain_comparison(self, metric, text, filters, max_leaves) -> ValueExplanation:
        rows = [dict(r) for r in (self.analytics.standard_vs_actual(filters).get("items") or [])]
        comparable = [r for r in rows if r.get("tempo_padrao_estimado_segundos") is not None and r.get("tempo_producao_real_segundos") is not None]
        no_standard = [r for r in rows if r.get("tempo_padrao_estimado_segundos") is None]
        no_real = [r for r in rows if r.get("tempo_padrao_estimado_segundos") is not None and r.get("tempo_producao_real_segundos") is None]
        expected = sum(float(r["tempo_padrao_estimado_segundos"]) for r in comparable)
        real = sum(float(r["tempo_producao_real_segundos"]) for r in comparable)
        notes = ["Só entram nos acumulados os apontamentos que têm tempo padrão E tempo real; os outros aparecem como excluídos."]

        if metric == "std.comparacoes":
            groups = [
                ("Com tempo padrão e tempo real", comparable),
                ("Sem tempo padrão cadastrado", no_standard),
                ("Com padrão, mas dados insuficientes de tempo real", no_real),
            ]
            children = [self._group(label, items, lambda r: 1.0, max_leaves) for label, items in groups if items]
            value = float(len(rows))
            reason = f"{len(rows)} apontamentos no período; {len(comparable)} têm padrão e tempo real."
            return self._build(metric, text, value, reason, children, [], notes,
                               reconciliation=_reconciliation(value, sum(c.value or 0.0 for c in children)))

        if metric == "std.desvio":
            has_base = bool(comparable) and expected > 0
            value = (real - expected) / expected * 100.0 if has_base else None
            if not has_base:
                reason = "Sem apontamentos com tempo padrão e tempo real no período: não há contra o que comparar."
                return self._build(metric, text, None, reason, [], [], notes)
            children = [
                ValueNode(kind="input", label="Tempo real acumulado", value=real, detail={"unidade": "segundos"}),
                ValueNode(kind="input", label="Tempo padrão acumulado", value=expected, detail={"unidade": "segundos"}),
            ]
            reason = f"Real {real / 3600:.2f} h contra padrão {expected / 3600:.2f} h em {len(comparable)} apontamentos."
            notes.append("As listas por trás de cada soma estão em “Tempo padrão acumulado” e “Tempo real acumulado”.")
            return self._build(metric, text, value, reason, children, [], notes,
                               reconciliation=_reconciliation(value, (real - expected) / expected * 100.0))

        key = "tempo_padrao_estimado_segundos" if metric == "std.padrao_acumulado" else "tempo_producao_real_segundos"
        total = expected if metric == "std.padrao_acumulado" else real
        children = self._by_resource(comparable, lambda r: float(r[key]) / 3600.0, max_leaves)
        excluded = []
        if no_standard:
            excluded.append({"label": "Apontamentos sem tempo padrão", "value": str(len(no_standard)),
                             "reason": "Sem padrão oficial (Protheus ou manual) não há tempo esperado."})
        if no_real:
            excluded.append({"label": "Apontamentos sem tempo real suficiente", "value": str(len(no_real)),
                             "reason": "Dados insuficientes de tempo real: ficam fora da soma para comparar o mesmo conjunto."})
        value = total / 3600.0
        reason = f"{len(comparable)} apontamentos comparáveis somam {value:.2f} h."
        return self._build(metric, text, value, reason, children, excluded, notes,
                           reconciliation=_reconciliation(value, sum(c.value or 0.0 for c in children)))

    def _group(self, label: str, items: list[dict], measure, max_leaves: int) -> ValueNode:
        leaves = [self._leaf(r, measure) for r in items[:max_leaves]]
        rest = items[max_leaves:]
        if rest:
            leaves.append(ValueNode(
                kind="event", label=f"Outros {len(rest)} apontamentos" if len(rest) > 1 else "Outro apontamento",
                value=sum(measure(r) for r in rest), truncated=True,
            ))
        return ValueNode(kind="group", label=label, value=sum(leaf.value or 0.0 for leaf in leaves), children=leaves,
                         truncated=any(leaf.truncated for leaf in leaves))

    def _by_resource(self, items: list[dict], measure, max_leaves: int) -> list[ValueNode]:
        grouped: dict[str, list[dict]] = {}
        for item in items:
            name = str(item.get("recurso_real") or item.get("recurso_previsto") or "").strip() or _NO_RESOURCE
            grouped.setdefault(name, []).append(item)
        nodes = []
        for name, group in grouped.items():
            node = self._group(name, group, measure, max_leaves)
            node.kind = "resource"
            nodes.append(node)
        nodes.sort(key=lambda n: -(n.value or 0.0))
        return nodes

    @staticmethod
    def _leaf(row: dict, measure) -> ValueNode:
        op = row.get("op")
        return ValueNode(
            kind="event",
            label=f"OP {op}" if op not in (None, "") else "Apontamento",
            value=measure(row),
            detail=_detail(
                operacao=row.get("operacao"),
                produto=row.get("produto"),
                recurso=row.get("recurso_real") or row.get("recurso_previsto"),
                boas=row.get("quantidade_boa"),
                padrao_por_peca=_fmt_s(row["tempo_padrao_unitario_segundos"]) if row.get("tempo_padrao_unitario_segundos") is not None else None,
                fonte_do_padrao=row.get("tempo_padrao_fonte"),
                real_por_peca=_fmt_s(row["tempo_real_por_peca_segundos"]) if row.get("tempo_real_por_peca_segundos") is not None else None,
            ),
        )

    # ------------------------------------------------------------------ comum

    def _build(self, metric, text, value, reason, children, excluded, notes, *, reconciliation=None) -> ValueExplanation:
        return ValueExplanation(
            metric=metric,
            label=text["label"],
            unit=text["unit"],
            value=value,
            reason=reason,
            rule=text["rule"],
            children=children,
            excluded=excluded,
            reconciliation=reconciliation or {"ok": True, "sum": None, "diff": None},
            calculated_at=self._now().isoformat(),
            truncated=_any_truncated(children),
            notes=notes,
        )

    def _now(self) -> datetime:
        clock = self._clock
        if callable(clock):
            moment = clock()
            if isinstance(moment, datetime):
                return moment
        return datetime.now()
