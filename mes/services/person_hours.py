"""Horas por funcionário (hora-homem) a partir de ``participacoes_operador``.

Cada pessoa conta o próprio tempo, sem dividir o tempo da OP. Quando a mesma
pessoa está em duas OPs simultâneas do mesmo posto (o card abre uma
participação por OP ativa), os intervalos são unidos: o mesmo minuto não conta
duas vezes. Participação aberta conta até agora (limitada ao fim do período).
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime


def _dt(value):
    """Data local sem fuso: misturar com e sem fuso quebraria a comparação."""
    if value is not None and not isinstance(value, datetime):
        try:
            value = datetime.fromisoformat(str(value))
        except (TypeError, ValueError):
            return None
    if value is not None and value.tzinfo is not None:
        value = value.astimezone().replace(tzinfo=None)
    return value


def _union_seconds(intervals) -> float:
    total = 0.0
    end = None
    for start, finish in sorted(intervals):
        if end is None or start > end:
            total += (finish - start).total_seconds()
            end = finish
        elif finish > end:
            total += (finish - end).total_seconds()
            end = finish
    return total


def horas_por_pessoa(rows, inicio: datetime, fim: datetime, agora: datetime) -> dict:
    inicio, fim, agora = _dt(inicio), _dt(fim), _dt(agora)
    limite = min(fim, agora)
    periodo_inclui_agora = inicio <= agora <= fim
    pessoas = {}
    for row in rows or ():
        cracha = str(row.get("cracha_resolvido") or row.get("cracha") or "").strip()
        comeco = _dt(row.get("data_inicio"))
        if not cracha or comeco is None:
            continue
        termino = _dt(row.get("data_fim"))
        start = max(comeco, inicio)
        end = min(termino or limite, fim)
        if end <= start:
            continue
        item = pessoas.setdefault(cracha, {
            "cracha": cracha,
            "nome": row.get("nome_resolvido") or row.get("nome") or cracha,
            "intervalos": [],
            "por_recurso": defaultdict(list),
            "ops": set(),
            "trabalhando_agora": False,
        })
        recurso = str(row.get("recurso") or "").strip() or "Não informado"
        item["intervalos"].append((start, end))
        item["por_recurso"][recurso].append((start, end))
        if row.get("op"):
            item["ops"].add(str(row["op"]))
        if termino is None and periodo_inclui_agora:
            item["trabalhando_agora"] = True

    result = []
    for item in pessoas.values():
        recursos = sorted(
            ({"recurso": recurso, "segundos": _union_seconds(parts)} for recurso, parts in item["por_recurso"].items()),
            key=lambda entry: -entry["segundos"],
        )
        result.append({
            "cracha": item["cracha"],
            "nome": item["nome"],
            "segundos": _union_seconds(item["intervalos"]),
            "recursos": recursos,
            "ops": len(item["ops"]),
            "trabalhando_agora": item["trabalhando_agora"],
        })
    result.sort(key=lambda entry: (-entry["segundos"], str(entry["nome"]).casefold()))
    return {
        "pessoas": result,
        "total_segundos": sum(entry["segundos"] for entry in result),
        "policy": "Cada pessoa conta o próprio tempo; o tempo da OP não é dividido nem multiplicado.",
    }
