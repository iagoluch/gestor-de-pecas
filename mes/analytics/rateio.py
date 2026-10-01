"""Rateio explícito de tempo sem confundir tempo físico com tempo atribuído."""

from collections import defaultdict
from typing import Hashable, Iterable, Mapping, Sequence

from app.core.resource_mapping import resolve_resource_identity
from mes.analytics.intervals import merge_intervals
from mes.domain import AllocationStrategy, EventCategory

# Estratégia aplicada quando várias OPs produzem no mesmo recurso ao mesmo
# tempo. Igualitária por padrão; a estratégia definitiva é decisão de negócio
# ainda não confirmada (AGENTS.md), por isso é uma constante única e visível.
CONCURRENT_PRODUCTION_STRATEGY = AllocationStrategy.EQUAL


def allocate_duration(
    physical_seconds: float,
    operation_keys: Sequence[str],
    *,
    strategy: AllocationStrategy,
    weights: Mapping[str, float] | None = None,
) -> dict[str, float]:
    """Distribui tempo físico sem criar minutos artificiais.

    A função não escolhe uma regra por conta própria. O chamador é obrigado a
    informar a estratégia. Em qualquer estratégia a soma atribuída é igual ao
    tempo físico (salvo arredondamento de ponto flutuante).
    """

    keys = [str(key) for key in operation_keys if str(key)]
    if not keys:
        return {}
    total = max(0.0, float(physical_seconds or 0))
    if strategy == AllocationStrategy.EQUAL:
        base = {key: 1.0 for key in keys}
    elif strategy in {
        AllocationStrategy.QUANTITY,
        AllocationStrategy.STANDARD_TIME,
        AllocationStrategy.PROPORTIONAL,
        AllocationStrategy.MANUAL,
    }:
        if not weights:
            raise ValueError(f"A estratégia {strategy.value} exige pesos explícitos.")
        base = {key: max(0.0, float(weights.get(key, 0) or 0)) for key in keys}
    else:  # defesa para enums futuros
        raise ValueError(f"Estratégia de rateio não suportada: {strategy}")

    weight_total = sum(base.values())
    if weight_total <= 0:
        raise ValueError("Os pesos do rateio devem possuir soma maior que zero.")

    result = {key: total * (weight / weight_total) for key, weight in base.items()}
    # Fecha a diferença de ponto flutuante no último item para garantir conservação.
    last = keys[-1]
    result[last] += total - sum(result.values())
    return result


def canonical_resource_key(resource) -> str:
    """Chave única do recurso físico: identidade canônica, sem caixa.

    Alias ("Laser Ensis 3015"), código ("LASER1") e variações de caixa do mesmo
    posto resultam na mesma chave. É a identidade usada pelo rateio e por quem
    agrupa o resultado dele (por exemplo, o arredondamento por recurso).
    """

    return str(resolve_resource_identity(resource) or resource or "").strip().upper()


def split_concurrent_time(
    entries: Iterable[tuple[Hashable, str, Iterable[tuple]]],
    *,
    strategy: AllocationStrategy = CONCURRENT_PRODUCTION_STRATEGY,
) -> dict[Hashable, float]:
    """Divide o tempo de recurso entre as OPs simultâneas, por derivação.

    Cada entrada é ``(chave_da_op, recurso, [(início, fim), ...])``. Em cada
    trecho elementar em que ``N`` OPs estão ativas no mesmo recurso, o trecho
    é distribuído por :func:`allocate_duration`. Assim o total por recurso é a
    união temporal dos intervalos — nunca a soma — e uma OP que produziu
    sozinha recebe o trecho inteiro. Não grava nada: o resultado é derivado dos
    próprios apontamentos, sem segunda fonte de verdade para o tempo.

    O agrupamento por recurso usa :func:`canonical_resource_key`, então alias,
    código e caixa diferentes do mesmo posto caem no mesmo grupo. Intervalos
    vazios são ignorados.
    """

    by_resource: dict[str, dict[Hashable, list]] = defaultdict(dict)
    for key, resource, intervals in entries:
        merged = merge_intervals(intervals)
        by_resource[canonical_resource_key(resource)][key] = merged
    result: dict[Hashable, float] = {}
    for per_key in by_resource.values():
        for key in per_key:
            result.setdefault(key, 0.0)
        bounds = sorted({edge for spans in per_key.values() for span in spans for edge in span})
        for start, end in zip(bounds, bounds[1:]):
            active = [
                key for key, spans in per_key.items()
                if any(s <= start and end <= e for s, e in spans)
            ]
            if not active:
                continue
            shares = allocate_duration(
                (end - start).total_seconds(),
                [str(index) for index in range(len(active))],
                strategy=strategy,
            )
            for index, key in enumerate(active):
                result[key] += shares[str(index)]
    return result


def split_concurrent_production(
    items: Iterable[tuple[Hashable, str, object]],
) -> dict[Hashable, float]:
    """``split_concurrent_time`` sobre o tempo de PRODUÇÃO de timelines de OP.

    Cada item é ``(chave, recurso_canônico, TimelineResult)``. Só os segmentos
    de produção entram: parada, setup e retrabalho continuam atribuídos
    integralmente à OP, como antes.
    """

    return split_concurrent_time(
        (
            key,
            resource,
            [
                (segment.start, segment.end)
                for segment in timeline.segments
                if segment.category == EventCategory.PRODUCTION
            ],
        )
        for key, resource, timeline in items
        if timeline is not None
    )
