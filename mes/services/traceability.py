"""Drill-down de OP até os fatos de origem disponíveis."""

from datetime import datetime

from app.core.operator_sectors import sector_display_label


def _dt(value):
    if value is None or isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def _timestamp(value):
    parsed = _dt(value)
    if parsed is None:
        return float("inf")
    if parsed.tzinfo is not None:
        return parsed.timestamp()
    return (parsed - datetime(1970, 1, 1)).total_seconds()


def _person_time_summary(participations):
    """Consolida o tempo-pessoa da OP a partir das participações.

    ``tempo_pessoa_segundos`` é a **soma** das pessoas e é maior que o tempo da
    OP quando mais de uma pessoa trabalhou junto. Isso é o resultado esperado,
    não duplo cômputo: são grandezas diferentes e o tempo da OP não é dividido.
    Participações ainda abertas não entram no total — tempo que não terminou
    não é tempo medido.
    """

    pessoas = {}
    total = 0.0
    abertas = 0
    for row in participations or ():
        inicio = _dt(row.get("data_inicio"))
        fim = _dt(row.get("data_fim"))
        chave = str(row.get("cracha") or row.get("nome") or "").strip()
        if chave:
            pessoas.setdefault(chave, {
                "cracha": row.get("cracha"),
                "nome": row.get("nome"),
                "segundos": 0.0,
                "participacoes": 0,
            })
        if fim is None or inicio is None:
            abertas += 1
            continue
        segundos = max(0.0, (fim - inicio).total_seconds())
        total += segundos
        if chave:
            pessoas[chave]["segundos"] += segundos
            pessoas[chave]["participacoes"] += 1
    return {
        "total_pessoas": len(pessoas),
        "tempo_pessoa_segundos": total,
        "participacoes_abertas": abertas,
        "pessoas": sorted(pessoas.values(), key=lambda item: -item["segundos"]),
        "source": "participacoes_operador",
        "policy": (
            "Tempo da OP e tempo-pessoa são grandezas distintas: o tempo da OP "
            "não é dividido entre as pessoas."
        ),
    }


class TraceabilityService:
    def __init__(self, db):
        self.db = db

    def trace_op(self, op: str) -> dict:
        code = str(op or "").strip()
        if not code:
            raise ValueError("OP é obrigatória para rastreabilidade.")

        # O período largo é apenas fallback para repositories cujo método exige
        # recorte. A implementação PostgreSQL filtra pela OP antes de materializar
        # os fatos e não varre a tabela inteira na UI.
        facts_loader = getattr(self.db, "listar_fatos_operacionais_periodo", None)
        facts = []
        if callable(facts_loader):
            facts = list(facts_loader(
                datetime(2000, 1, 1), datetime(2100, 1, 1), op=code
            ) or [])

        quantity_loader = getattr(self.db, "listar_eventos_quantidade_periodo", None)
        quantities = []
        if callable(quantity_loader):
            quantities = list(quantity_loader(
                datetime(2000, 1, 1), datetime(2100, 1, 1), op=code
            ) or [])

        nesting_loader = getattr(self.db, "listar_nestings_corte_por_op", None)
        nestings = list(nesting_loader(code) or []) if callable(nesting_loader) else []

        states_loader = getattr(self.db, "listar_estados_recurso_periodo", None)
        physical_states = list(states_loader(
            datetime(2000, 1, 1), datetime(2100, 1, 1), op=code
        ) or []) if callable(states_loader) else []

        rateio_loader = getattr(self.db, "listar_rateios_tempo_periodo", None)
        rateio_sessions = list(rateio_loader(
            datetime(2000, 1, 1), datetime(2100, 1, 1), op=code
        ) or []) if callable(rateio_loader) else []

        participation_loader = getattr(self.db, "listar_participacoes_operador_periodo", None)
        operator_participations = list(participation_loader(
            datetime(2000, 1, 1), datetime(2100, 1, 1), op=code
        ) or []) if callable(participation_loader) else []

        legacy_loader = getattr(self.db, "get_op_timeline", None)
        legacy_timeline = list(legacy_loader(code) or []) if callable(legacy_loader) else []

        operations = []
        for fact in facts:
            operations.append({
                "apontamento_id": fact.get("id"),
                "operacao": fact.get("numero_operacao"),
                "descricao_operacao": fact.get("descricao_operacao"),
                "produto": fact.get("produto_codigo") or fact.get("peca"),
                "recurso_previsto": fact.get("codigo_recurso"),
                "recurso_real": fact.get("maquina"),
                "setor": fact.get("tipo_setor"),
                # Wave 5.1 — apontamento em setor incorreto: origem preservada.
                "setor_roteiro": fact.get("setor_roteiro"),
                "setor_divergente": bool(fact.get("setor_divergente")),
                "setor_exibicao": sector_display_label(
                    fact.get("tipo_setor"), fact.get("setor_roteiro")
                ),
                "status": fact.get("status"),
                "inicio": fact.get("data_inicio"),
                "fim": fact.get("data_fim"),
                "quantidade_boa": int(fact.get("quantidade_boa") or 0),
                "refugo": int(fact.get("quantidade_refugo") or 0),
                "retrabalho": int(fact.get("quantidade_retrabalho") or 0),
                "lote": fact.get("lote"),
                "eventos": list(fact.get("eventos") or []),
            })

        timeline = []
        for operation in operations:
            if operation.get("inicio"):
                timeline.append({
                    "timestamp": operation.get("inicio"),
                    "type": "inicio_operacao",
                    "status": operation.get("status"),
                    "reason": operation.get("descricao_operacao"),
                    "operator": None,
                    "resource": operation.get("recurso_real"),
                    "operation": operation.get("operacao"),
                    "source": "apontamentos_operacionais",
                    "record_id": operation.get("apontamento_id"),
                    "appointment_id": operation.get("apontamento_id"),
                })
            for event in operation.get("eventos") or []:
                timeline.append({
                    "timestamp": event.get("data_hora"),
                    "type": event.get("tipo_evento") or event.get("tipo") or "evento_operacional",
                    "status": event.get("status_novo") or event.get("status"),
                    "reason": event.get("motivo") or event.get("comentario"),
                    "operator": event.get("operador") or event.get("operador_nome"),
                    "resource": operation.get("recurso_real"),
                    "operation": operation.get("operacao"),
                    "source": "eventos_apontamento_operador",
                    "record_id": event.get("id"),
                    "appointment_id": operation.get("apontamento_id"),
                })
            if operation.get("fim"):
                timeline.append({
                    "timestamp": operation.get("fim"),
                    "type": "fim_operacao",
                    "status": operation.get("status"),
                    "reason": operation.get("descricao_operacao"),
                    "operator": None,
                    "resource": operation.get("recurso_real"),
                    "operation": operation.get("operacao"),
                    "source": "apontamentos_operacionais",
                    "record_id": operation.get("apontamento_id"),
                    "appointment_id": operation.get("apontamento_id"),
                })
        for event in quantities:
            timeline.append({
                "timestamp": event.get("data_hora"),
                "type": f"quantidade_{event.get('tipo') or 'nao_informada'}",
                "status": None,
                "reason": event.get("motivo"),
                "operator": event.get("operador"),
                "resource": event.get("recurso"),
                "operation": event.get("numero_operacao"),
                "source": "eventos_quantidade_producao",
                "record_id": event.get("id"),
                "appointment_id": event.get("apontamento_id"),
                "quantity": event.get("quantidade"),
            })
        for state in physical_states:
            timeline.append({
                "timestamp": state.get("data_inicio") or state.get("inicio"),
                "type": "estado_fisico_recurso",
                "status": state.get("categoria") or state.get("codigo_status"),
                "reason": state.get("motivo") or state.get("causa_raiz"),
                "operator": state.get("operador"),
                "resource": state.get("recurso"),
                "operation": state.get("numero_operacao"),
                "source": "eventos_estado_recurso",
                "record_id": state.get("id"),
                "appointment_id": state.get("apontamento_id"),
            })
        for participation in operator_participations:
            timeline.append({
                "timestamp": participation.get("data_inicio") or participation.get("inicio"),
                "type": "participacao_operador",
                "status": participation.get("status"),
                "reason": participation.get("tipo_participacao"),
                "operator": participation.get("nome") or participation.get("cracha"),
                "resource": participation.get("recurso"),
                "operation": participation.get("numero_operacao"),
                "source": "participacoes_operador",
                "record_id": participation.get("id"),
                "appointment_id": participation.get("apontamento_id"),
            })
        for nesting in nestings:
            timeline.append({
                "timestamp": nesting.get("inicio"),
                "type": "inicio_nesting",
                "status": nesting.get("status"),
                "reason": nesting.get("programa") or nesting.get("tarefa"),
                "operator": nesting.get("operador_inicio"),
                "resource": nesting.get("maquina"),
                "operation": "Corte",
                "source": "apontamentos_corte",
                "record_id": nesting.get("apontamento_id"),
                "appointment_id": nesting.get("apontamento_id"),
                "nesting": nesting.get("nesting"),
            })
        for movement in legacy_timeline:
            timeline.append({
                "timestamp": movement.get("data_hora") or movement.get("data"),
                "type": movement.get("tipo") or "movimento_legado",
                "status": movement.get("status"),
                "reason": movement.get("motivo"),
                "operator": movement.get("operador"),
                "resource": movement.get("recurso") or movement.get("maquina"),
                "operation": movement.get("operacao"),
                "source": "historico_legado",
                "record_id": movement.get("id"),
                "appointment_id": movement.get("apontamento_id"),
            })
        timeline.sort(key=lambda item: (_timestamp(item.get("timestamp")), item.get("record_id") or 0))

        return {
            "op": code,
            "operations": operations,
            "quantity_events": quantities,
            "cutting_nestings": nestings,
            "physical_states": physical_states,
            "rateio_sessions": rateio_sessions,
            "operator_participations": operator_participations,
            # Tempo-pessoa da OP: soma das participações. Não é o tempo da OP e
            # não deve ser comparado com ele como se fossem a mesma grandeza.
            "person_time": _person_time_summary(operator_participations),
            "legacy_movements": legacy_timeline,
            "timeline": timeline,
            "source_refs": {
                "operations": [row.get("apontamento_id") for row in operations if row.get("apontamento_id")],
                "quantity_events": [row.get("id") for row in quantities if row.get("id")],
                "cutting_nestings": [row.get("apontamento_id") for row in nestings if row.get("apontamento_id")],
                "physical_states": [row.get("id") for row in physical_states if row.get("id")],
                "rateio_sessions": [row.get("id") for row in rateio_sessions if row.get("id")],
                "operator_participations": [row.get("id") for row in operator_participations if row.get("id")],
            },
        }
