"""split_concurrent_time por varredura == versão antiga (quadrática), bit a bit."""

from collections import defaultdict
from datetime import datetime, timedelta
import random
import time
import unittest

from mes.analytics.intervals import merge_intervals
from mes.analytics.rateio import allocate_duration, canonical_resource_key, split_concurrent_time
from mes.domain import AllocationStrategy

T0 = datetime(2026, 10, 1, 8, 0)


def _referencia(entries, strategy=AllocationStrategy.EQUAL):
    """Cópia da implementação anterior (testa todo trecho contra todo intervalo)."""
    by_resource = defaultdict(dict)
    for key, resource, intervals in entries:
        by_resource[canonical_resource_key(resource)][key] = merge_intervals(intervals)
    result = {}
    for per_key in by_resource.values():
        for key in per_key:
            result.setdefault(key, 0.0)
        bounds = sorted({edge for spans in per_key.values() for span in spans for edge in span})
        for start, end in zip(bounds, bounds[1:]):
            active = [k for k, spans in per_key.items() if any(s <= start and end <= e for s, e in spans)]
            if not active:
                continue
            shares = allocate_duration((end - start).total_seconds(), [str(i) for i in range(len(active))], strategy=strategy)
            for index, key in enumerate(active):
                result[key] += shares[str(index)]
    return result


def _entries(rng, ops, recursos, spans_por_op):
    entries = []
    for op in range(ops):
        intervals = []
        for _ in range(rng.randint(0, spans_por_op)):
            start = T0 + timedelta(minutes=rng.randint(0, 600))
            intervals.append((start, start + timedelta(minutes=rng.randint(-5, 90))))
        entries.append((f"op{op}", rng.choice(recursos), intervals))
    return entries


class RateioEquivalenciaTests(unittest.TestCase):
    def test_aleatorio_identico_a_referencia(self):
        rng = random.Random(20261008)
        for _ in range(300):
            entries = _entries(rng, rng.randint(1, 12), ["LASER1", "Laser Ensis 3015", "PLASMA1"], 5)
            self.assertEqual(split_concurrent_time(entries), _referencia(entries))

    def test_ops_encostadas_no_mesmo_instante(self):
        entries = [
            ("a", "R1", [(T0, T0 + timedelta(minutes=10))]),
            ("b", "R1", [(T0 + timedelta(minutes=10), T0 + timedelta(minutes=20))]),
            ("c", "R1", [(T0 + timedelta(minutes=5), T0 + timedelta(minutes=15))]),
        ]
        resultado = split_concurrent_time(entries)
        self.assertEqual(resultado, _referencia(entries))
        self.assertAlmostEqual(sum(resultado.values()), 20 * 60)

    def test_volume_grande_termina_rapido(self):
        entries = _entries(random.Random(1), 1500, ["R1"], 4)
        inicio = time.perf_counter()
        split_concurrent_time(entries)
        self.assertLess(time.perf_counter() - inicio, 5.0)


if __name__ == "__main__":
    unittest.main()
