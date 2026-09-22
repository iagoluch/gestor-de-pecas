"""Álgebra de intervalos temporais compartilhada pelas análises.

A união de intervalos que se tocam ou se sobrepõem é a mesma operação para o
calendário produtivo (janelas de turno, hora extra, fora de turno) e para a
consolidação de tempo físico por recurso. Manter uma cópia por módulo já
produziu duas definições idênticas; como o resultado vira segundos
contabilizados em disponibilidade e OEE, a regra precisa de uma fonte de
verdade só.

Mora em ``analytics`` porque é a camada mais baixa das duas: ``mes.services``
importa ``mes.analytics``, nunca o contrário.
"""

from __future__ import annotations


def merge_intervals(intervals):
    """Une intervalos sobrepostos ou adjacentes, descartando os vazios.

    Recebe pares ``(início, fim)`` de qualquer tipo ordenável (na prática,
    ``datetime``) e devolve uma lista ordenada de tuplas disjuntas. Intervalos
    com ``fim <= início`` são ignorados — não representam tempo decorrido.
    """

    ordered = sorted(
        ((start, end) for start, end in intervals if end > start),
        key=lambda item: (item[0], item[1]),
    )
    merged = []
    for start, end in ordered:
        if not merged or start > merged[-1][1]:
            merged.append([start, end])
        else:
            merged[-1][1] = max(merged[-1][1], end)
    return [(start, end) for start, end in merged]


__all__ = ["merge_intervals"]
