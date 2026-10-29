"""Aproveitamento da chapa no Corte (somente leitura).

O SigmaNEST informa, por nesting, ``UsedArea`` e ``ScrapFraction``. Eles são
gravados em ``apontamentos_corte.area_usada`` e ``fracao_sucata`` sem a área
total da chapa, então a única conta disponível é::

    aproveitamento = (1 - fracao_sucata) x 100

Fração fora de 0..1 (ou ausente) não vira número: fica ``None`` e o nesting é
contado como "sem dado". A média do período é a média simples por nesting.
"""

from __future__ import annotations

UTILIZATION_RULE = (
    "Aproveitamento = (1 - fração de sucata) x 100, por nesting. A média é "
    "simples por nesting com dado; a área total da chapa não é gravada."
)


def _number(value):
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def aproveitamento_percentual(fracao_sucata):
    """Percentual aproveitado da chapa, ou ``None`` quando o dado não permite."""

    fraction = _number(fracao_sucata)
    if fraction is None or not 0.0 <= fraction <= 1.0:
        return None
    return round((1.0 - fraction) * 100.0, 2)


def com_aproveitamento(row: dict) -> dict:
    """Cópia da linha de nesting com ``aproveitamento_percentual`` calculado."""

    return {**row, "aproveitamento_percentual": aproveitamento_percentual(row.get("fracao_sucata"))}


def _mean(values):
    return round(sum(values) / len(values), 2) if values else None


def resumir_aproveitamento(items) -> dict:
    """Total do conjunto de nestings e quebra por tarefa de corte."""

    rows = [row for row in (items or ()) if isinstance(row, dict)]
    by_task: dict = {}
    all_values: list[float] = []
    for row in rows:
        value = aproveitamento_percentual(row.get("fracao_sucata"))
        bucket = by_task.setdefault(row.get("tarefa"), {
            "tarefa": row.get("tarefa"),
            "nestings": 0,
            "nestings_com_dado": 0,
            "area_usada": 0.0,
            "_values": [],
        })
        bucket["nestings"] += 1
        bucket["area_usada"] += _number(row.get("area_usada")) or 0.0
        if value is not None:
            bucket["nestings_com_dado"] += 1
            bucket["_values"].append(value)
            all_values.append(value)
    tasks = []
    for bucket in by_task.values():
        values = bucket.pop("_values")
        tasks.append({**bucket, "aproveitamento_medio_percentual": _mean(values)})
    return {
        "nestings": len(rows),
        "nestings_com_dado": len(all_values),
        "nestings_sem_dado": len(rows) - len(all_values),
        "area_usada_total": sum(_number(row.get("area_usada")) or 0.0 for row in rows),
        "aproveitamento_medio_percentual": _mean(all_values),
        "por_tarefa": tasks,
        "regra": UTILIZATION_RULE,
    }
