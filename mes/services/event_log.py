"""Eventos de Status e Eventos de Produção para a Auditoria.

Dois livros separados, de propósito:

* **Status** explica o uso do tempo do recurso (``eventos_estado_recurso``),
  produzindo ou parado. Um status sozinho não prova que uma OP foi executada.
* **Produção** explica o trabalho feito nesse tempo: o apontamento (OP,
  produto, operação, recurso, colaborador) aberto por atividade, com o tempo
  vindo dos estados ligados ao apontamento e as quantidades vindas da tabela
  de peças (``eventos_quantidade_producao``).

Cada evento de quantidade é atribuído a um único evento de produção (pela OP e
operação), então nenhuma quantidade é contada duas vezes. Quantidade sem
apontamento correspondente vira linha própria, visível, em vez de sumir.
Nenhuma regra de OEE é recalculada aqui.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime

from app.core.resource_mapping import resolve_resource_identity, resource_display_name
from mes.analytics.resource_state import classify_state_row, physical_state_category
from mes.domain import EventCategory, QuantityKind


#: Estados que representam trabalho de um apontamento.
_WORK_CATEGORIES = (EventCategory.PRODUCTION, EventCategory.SETUP, EventCategory.REWORK)


def _key(value) -> str:
    return str(value or "").strip().upper()


def _value(classification):
    return getattr(classification, "value", classification)


def _status_class(category: str, classification) -> str:
    """Uma chave só para filtrar: parada já vem separada em planejada / não planejada."""

    if category == EventCategory.DOWNTIME.value and classification:
        return f"parada_{classification}"
    return category


def status_events(states, *, operador=None, recurso=None, status=None, classe=None, op=None, em_aberto=False, nomes=None):
    """Projeção dos estados físicos do período, um por linha.

    ``opcoes`` lista os recursos, status e classes do período inteiro (antes
    dos filtros da tabela), para a tela montar as listas de escolha.
    ``nomes`` (código em minúsculas -> nome do catálogo) dá o nome líquido do
    recurso; ``recurso`` segue sendo o código, que é a identidade do filtro.
    """

    nomes = nomes or {}

    alvo = str(operador or "").strip().casefold()
    all_items = []
    for row in states or []:
        if alvo and alvo not in str(row.get("operador") or "").casefold():
            continue
        category = physical_state_category(row)
        classification = _value(classify_state_row(row))
        all_items.append({
            "id": row.get("id"),
            "recurso": row.get("recurso"),
            "recurso_nome": resource_display_name(row.get("recurso"), nomes.get(str(row.get("recurso") or "").strip().casefold())) or None,
            "setor": row.get("tipo_setor"),
            "codigo_status": row.get("codigo_status_recurso"),
            "descricao": row.get("status_nome"),
            "categoria": category.value,
            "classificacao": classification,
            "classe": _status_class(category.value, classification),
            "inicio": row.get("data_inicio"),
            "fim": row.get("data_fim"),
            "em_aberto": row.get("data_fim") is None,
            "duracao_segundos": row.get("segundos_periodo"),
            "operador": row.get("operador"),
            "motivo": row.get("motivo"),
            "comentario": row.get("comentario"),
            "op": row.get("op"),
            "operacao": row.get("numero_operacao"),
            "origem": row.get("origem"),
        })

    def options(field):
        return sorted({str(item[field]) for item in all_items if item[field]}, key=str.casefold)

    # Um item por recurso (o filtro ignora maiúsculas: "Jato" e "JATO" são um só).
    resources = {}
    for item in all_items:
        if item["recurso"]:
            resources.setdefault(_key(item["recurso"]), {"codigo": item["recurso"], "nome": item["recurso_nome"] or item["recurso"]})
    resource_options = sorted(resources.values(), key=lambda option: option["nome"].casefold())

    wanted = {
        "recurso": _key(recurso),
        "descricao": _key(status),
        "classe": str(classe or "").strip(),
    }
    op_text = _key(op)
    items = [
        item for item in all_items
        if all(not value or _key(item[field]) == _key(value) for field, value in wanted.items())
        and (not op_text or op_text in _key(item["op"]))
        and (not em_aberto or item["em_aberto"])
    ]
    items.sort(key=lambda item: (str(item["inicio"] or ""), str(item["recurso"] or "")), reverse=True)
    return {
        "opcoes": {"recursos": resource_options, "status": options("descricao"), "classes": options("classe")},
        "items": items,
        "summary": {
            "eventos": len(items),
            "recursos": len({item["recurso"] for item in items if item["recurso"]}),
            "paradas_nao_planejadas": sum(1 for item in items if item["classificacao"] == "nao_planejada"),
            "em_aberto": sum(1 for item in items if item["em_aberto"]),
        },
    }


def _resource_identity(value) -> str:
    text = str(value or "").strip()
    return str(resolve_resource_identity(text) or text).strip().upper()


def _operator_intervals(events, end_of):
    """Intervalos de trabalho de cada apontamento pelos cliques do operador.

    ``producao``/``setup``/``retrabalho`` abrem um intervalo daquela
    atividade; ``fila``/``parada``/``finalizado``/``parcial`` fecham (a
    finalização parcial devolve a OP para Aguardando). Intervalo ainda aberto termina em ``end_of[id]`` (fim do
    apontamento) ou fica aberto (``None``).
    """

    by_id = defaultdict(list)
    for event in events or []:
        if event.get("apontamento_id") is not None and isinstance(event.get("data_hora"), datetime):
            by_id[event["apontamento_id"]].append(event)
    work_values = {category.value for category in _WORK_CATEGORIES}
    result = {}
    for appointment_id, rows in by_id.items():
        rows.sort(key=lambda row: (row["data_hora"], row.get("id") or 0))
        intervals = []
        current = None
        for row in rows:
            state = str(row.get("estado") or "")
            if current is not None:
                intervals.append((current[0], current[1], row["data_hora"]))
                current = None
            if state in work_values:
                current = (state, row["data_hora"])
        if current is not None:
            intervals.append((current[0], current[1], end_of.get(appointment_id)))
        result[appointment_id] = intervals
    return result


def _work_by_appointment(states, facts=(), operator_events=None):
    """Tempo de trabalho de cada apontamento, por atividade.

    Com os eventos do operador, cada OP recebe o tempo inteiro em que esteve
    ativa, recortado pelo tempo em que o posto de fato trabalhou (produção,
    setup ou retrabalho físico). OPs simultâneas no mesmo posto mostram,
    cada uma, o tempo todo, sem divisão (decisão da manufatura, 11/11/2026);
    intervalo, fora de turno e parada do posto não entram. Sem eventos do
    operador, vale o vínculo do estado físico com o apontamento.
    """

    grouped = defaultdict(lambda: defaultdict(list))
    end_of = {
        fact.get("id"): fact.get("data_fim") for fact in facts or []
        if isinstance(fact.get("data_fim"), datetime)
    }
    intervals = _operator_intervals(operator_events, end_of) if operator_events else {}
    if intervals:
        physical = defaultdict(list)
        for row in states or []:
            if str(row.get("categoria") or "") in {category.value for category in _WORK_CATEGORIES}:
                physical[_resource_identity(row.get("recurso"))].append(row)
        for fact in facts or []:
            appointment_id = fact.get("id")
            if appointment_id not in intervals:
                continue
            rows = physical.get(_resource_identity(fact.get("maquina") or fact.get("codigo_recurso")), [])
            for activity, start, end in intervals[appointment_id]:
                for row in rows:
                    row_start, row_end = row.get("inicio_periodo"), row.get("fim_periodo")
                    if not isinstance(row_start, datetime) or not isinstance(row_end, datetime):
                        continue
                    clip_start = max(start, row_start)
                    clip_end = row_end if end is None else min(end, row_end)
                    if clip_end <= clip_start:
                        continue
                    grouped[appointment_id][activity].append({
                        "inicio_periodo": clip_start,
                        "fim_periodo": clip_end,
                        "segundos_periodo": (clip_end - clip_start).total_seconds(),
                        "data_fim": None if end is None and row.get("data_fim") is None else clip_end,
                    })
    # Apontamento já resolvido pelos cliques não repete o vínculo físico;
    # sem cruzamento (posto com outro nome), vale o vínculo antigo.
    resolved = set(grouped)
    for row in states or []:
        if row.get("apontamento_id") in resolved:
            continue
        if row.get("apontamento_id") is None:
            continue
        try:
            category = EventCategory(str(row.get("categoria") or ""))
        except ValueError:
            continue
        if category in _WORK_CATEGORIES:
            grouped[row["apontamento_id"]][category.value].append(row)
    return grouped


def _assign_quantities(facts, quantities):
    """Liga cada evento de quantidade a um único apontamento.

    Candidatos: mesma OP e operação. Preferência: o apontamento cujo intervalo
    contém o instante da quantidade (no mesmo recurso, se houver), senão o
    último iniciado antes dela. Apontamento iniciado depois da quantidade não
    é candidato. Sem candidato, a quantidade fica órfã.
    """

    by_key = defaultdict(list)
    for fact in facts:
        by_key[(_key(fact.get("op")), _key(fact.get("numero_operacao")))].append(fact)
    assigned = defaultdict(list)
    orphans = []
    for event in quantities or []:
        candidates = by_key.get((_key(event.get("op")), _key(event.get("numero_operacao"))), [])
        moment = event.get("data_hora")
        best = None
        best_rank = None
        for fact in candidates:
            start = fact.get("data_inicio") or fact.get("data_entrada")
            end = fact.get("data_fim")
            if isinstance(moment, datetime) and isinstance(start, datetime) and start > moment:
                # Quantidade anterior ao início do apontamento não é dele: se não
                # houver outro candidato, fica órfã e aparece como inconsistência.
                continue
            else:
                inside = end is None or not isinstance(moment, datetime) or moment <= end
                same_resource = _key(event.get("recurso")) in {_key(fact.get("codigo_recurso")), _key(fact.get("maquina"))}
                distance = (
                    (moment - start).total_seconds()
                    if isinstance(moment, datetime) and isinstance(start, datetime)
                    else 0.0
                )
                rank = (0 if inside and same_resource else 1 if inside else 2, distance)
            if best_rank is None or rank < best_rank:
                best, best_rank = fact, rank
        if best is None:
            orphans.append(event)
        else:
            assigned[best.get("id")].append(event)
    return assigned, orphans


def _sum_quantities(events):
    total = {kind.value: 0 for kind in QuantityKind}
    for event in events:
        kind = str(event.get("tipo") or "")
        if kind in total:
            total[kind] += int(event.get("quantidade") or 0)
    return total


def production_events(facts, states, quantities, cuts=(), operator_events=None):
    facts = list(facts or [])
    work = _work_by_appointment(states, facts, operator_events)
    assigned, orphans = _assign_quantities(facts, quantities)
    items = []

    for fact in facts:
        base = {
            "apontamento_id": fact.get("id"),
            "op": fact.get("op"),
            "produto": fact.get("produto_codigo") or fact.get("peca"),
            "produto_descricao": fact.get("produto_descricao"),
            "operacao": fact.get("numero_operacao"),
            "descricao_operacao": fact.get("descricao_operacao"),
            "setor": fact.get("tipo_setor"),
            "recurso": fact.get("maquina") or fact.get("codigo_recurso"),
            "colaborador": fact.get("operador_inicio_nome") or fact.get("operador_inicio") or fact.get("operador_fim"),
            "tempo_padrao_segundos": fact.get("tempo_padrao_segundos"),
            "tempo_padrao_fonte": fact.get("tempo_padrao_fonte"),
            "status_apontamento": fact.get("status"),
        }
        default_activity = (
            EventCategory.REWORK.value if fact.get("retorno_retrabalho_qualidade") else EventCategory.PRODUCTION.value
        )
        activities = work.get(fact.get("id")) or {}
        rows = []
        for activity, segments in activities.items():
            rows.append({
                **base,
                "atividade": activity,
                "inicio": min(segment.get("inicio_periodo") for segment in segments),
                "fim": None if any(segment.get("data_fim") is None for segment in segments)
                else max(segment.get("fim_periodo") for segment in segments),
                "tempo_real_segundos": sum(float(segment.get("segundos_periodo") or 0) for segment in segments),
            })
        if not rows:
            rows.append({
                **base,
                "atividade": default_activity,
                "inicio": fact.get("data_inicio") or fact.get("data_entrada"),
                "fim": fact.get("data_fim"),
                "tempo_real_segundos": None,
            })
        rows.sort(key=lambda row: str(row["inicio"] or ""))
        # Quantidade entra numa linha só: a de produção/retrabalho, nunca no setup
        # quando há outra atividade.
        target = next((row for row in rows if row["atividade"] != EventCategory.SETUP.value), rows[-1])
        totals = _sum_quantities(assigned.get(fact.get("id"), []))
        for row in rows:
            source = totals if row is target else {kind: None for kind in totals}
            row.update({
                "quantidade_boa": source[QuantityKind.GOOD.value],
                "quantidade_refugo": source[QuantityKind.SCRAP.value],
                "quantidade_retrabalho": source[QuantityKind.REWORK.value],
                "inconsistencia": None,
            })
        items.extend(rows)

    for event in orphans:
        totals = _sum_quantities([event])
        items.append({
            "apontamento_id": None,
            "op": event.get("op"),
            "produto": event.get("produto_codigo"),
            "produto_descricao": None,
            "operacao": event.get("numero_operacao"),
            "descricao_operacao": None,
            "setor": event.get("tipo_setor"),
            "recurso": event.get("recurso"),
            "colaborador": event.get("operador"),
            "tempo_padrao_segundos": None,
            "tempo_padrao_fonte": None,
            "status_apontamento": None,
            "atividade": None,
            "inicio": event.get("data_hora"),
            "fim": event.get("data_hora"),
            "tempo_real_segundos": None,
            "quantidade_boa": totals[QuantityKind.GOOD.value],
            "quantidade_refugo": totals[QuantityKind.SCRAP.value],
            "quantidade_retrabalho": totals[QuantityKind.REWORK.value],
            "inconsistencia": "quantidade_sem_evento",
        })

    # Corte: identificado por tarefa e plano; não soma peças por OP aqui.
    for cut in cuts or []:
        items.append({
            "apontamento_id": None,
            "op": None,
            "tarefa": cut.get("codigo_tarefa"),
            "plano": cut.get("programa") or cut.get("nome_chapa"),
            "produto": None,
            "produto_descricao": cut.get("material"),
            "operacao": None,
            "descricao_operacao": "Corte do plano",
            "setor": "CORTE",
            "recurso": cut.get("maquina"),
            "colaborador": cut.get("operador_inicio") or cut.get("operador_fim"),
            "tempo_padrao_segundos": cut.get("tempo_previsto_segundos"),
            "tempo_padrao_fonte": "sigmanest" if cut.get("tempo_previsto_segundos") is not None else None,
            "status_apontamento": cut.get("status"),
            "atividade": EventCategory.PRODUCTION.value,
            "inicio": cut.get("data_inicio"),
            "fim": cut.get("data_fim"),
            "tempo_real_segundos": cut.get("tempo_real_segundos"),
            "quantidade_boa": None,
            "quantidade_refugo": None,
            "quantidade_retrabalho": None,
            "inconsistencia": None,
        })

    items.sort(key=lambda item: (str(item["inicio"] or ""), str(item["recurso"] or "")), reverse=True)

    def total(field):
        return sum(int(item[field] or 0) for item in items)

    return {
        "items": items,
        "summary": {
            "eventos": len(items),
            "quantidade_boa": total("quantidade_boa"),
            "quantidade_refugo": total("quantidade_refugo"),
            "quantidade_retrabalho": total("quantidade_retrabalho"),
            "quantidade_sem_evento": len(orphans),
        },
    }
