"""Rateio explícito de tempo sem confundir tempo físico com tempo atribuído."""

from typing import Mapping, Sequence

from mes.domain import AllocationStrategy


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
