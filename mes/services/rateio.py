"""Serviço de rateio que preserva o tempo físico do recurso."""

from mes.analytics.rateio import allocate_duration
from mes.domain import AllocationStrategy


class RateioService:
    def __init__(self, db):
        self.db = db

    def registrar(
        self, recurso, inicio, fim, operations, *, strategy, weights=None,
        tipo_setor=None, referencia_origem=None,
    ):
        strategy = strategy if isinstance(strategy, AllocationStrategy) else AllocationStrategy(str(strategy))
        keys = [self._key(item) for item in operations]
        if len(keys) != len(set(keys)):
            raise ValueError("Cada OP/operação deve aparecer uma única vez na mesma sessão de rateio.")
        physical = max(0.0, (fim - inicio).total_seconds())
        allocated = allocate_duration(
            physical,
            keys,
            strategy=strategy,
            weights=weights,
        )
        rows = []
        for item, key in zip(operations, keys):
            rows.append({
                "op": item.get("op"),
                "numero_operacao": item.get("numero_operacao"),
                "estrategia": strategy.value,
                "peso": (weights or {}).get(key) if weights else None,
                "segundos_atribuidos": allocated[key],
            })
        return self.db.registrar_rateio_recurso(
            recurso,
            inicio,
            fim,
            rows,
            tipo_setor=tipo_setor,
            origem="rateio_service",
            referencia_origem=referencia_origem,
        )

    @staticmethod
    def _key(item):
        op = str(item.get("op") or "").strip()
        operation = str(item.get("numero_operacao") or "").strip()
        if not op:
            raise ValueError("Cada item de rateio deve possuir OP.")
        return f"{op}:{operation}"
