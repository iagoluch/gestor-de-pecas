"""OPs simultâneas no mesmo recurso: regra de ocupação e tempo por crachá.

O rateio igualitário por recurso (01/10/2026) foi substituído pela
Metodologia de Tempos e Rateios V2 (13/11/2026): divide só o crachá que
atende várias OPs ao mesmo tempo. Cenários do documento em
``test_rateio_por_cracha.py``; aqui ficam ocupação, identidade do recurso e
o uso da timeline real.
"""

from datetime import datetime, timedelta
import unittest

from mes.analytics.physical_time import PhysicalInputSegment, consolidate_physical_time
from mes.analytics.rateio import allocate_by_badge, canonical_resource_key, production_spans
from mes.analytics.timeline import build_operator_timeline
from mes.domain import EventCategory, OperatorState, resource_concurrency_conflict

T0 = datetime(2026, 10, 1, 8, 0)


def _min(n):
    return T0 + timedelta(minutes=n)


class RegraDeOcupacaoTests(unittest.TestCase):
    Q, P, S, R, F = (
        OperatorState.QUEUED, OperatorState.PRODUCTION, OperatorState.STOPPED,
        OperatorState.SETUP, OperatorState.REWORK,
    )

    def test_recurso_livre_nunca_conflita(self):
        for destino in (self.P, self.S, self.R):
            self.assertFalse(resource_concurrency_conflict(self.Q, destino, []))

    def test_producao_com_producao_e_com_parada_e_permitida(self):
        self.assertFalse(resource_concurrency_conflict(self.Q, self.P, ["Em processo"]))
        self.assertFalse(resource_concurrency_conflict(self.Q, self.P, ["Em processo", "Em processo"]))
        self.assertFalse(resource_concurrency_conflict(self.S, self.P, ["Parada"]))
        self.assertFalse(resource_concurrency_conflict(self.P, self.S, ["Em processo"]))

    def test_recurso_aceita_qualquer_estado_com_outras_ops_ativas(self):
        # Decisão do usuário (10/11/2026): várias OPs no recurso,
        # independente do apontamento atual. Setup/Retrabalho não são mais
        # exclusivos, e Parada direto da fila também passa.
        ocupacoes = (["Em processo"], ["Setup"], ["Retrabalho"], ["Parada"],
                     ["Em processo", "Retrabalho"])
        for outros in ocupacoes:
            for origem, destino in ((self.Q, self.P), (self.Q, self.R), (self.Q, self.F),
                                    (self.Q, self.S), (self.P, self.R), (self.S, self.P)):
                with self.subTest(origem=origem, destino=destino, outros=outros):
                    self.assertFalse(resource_concurrency_conflict(origem, destino, outros))



class TempoPorCrachaNoRecursoTests(unittest.TestCase):
    def test_alias_codigo_e_caixa_sao_o_mesmo_recurso(self):
        # Mesmo crachá em "LASER1" e no alias do mesmo posto não é conflito.
        self.assertEqual(canonical_resource_key("Laser Ensis 3015"), "LASER1")
        self.assertEqual(canonical_resource_key("laser1"), "LASER1")
        result = allocate_by_badge(
            [("A", "LASER1", [(_min(0), _min(60))]),
             ("B", "Laser Ensis 3015", [(_min(0), _min(60))]),
             ("C", "laser1", [(_min(0), _min(60))])],
            [(key, "C1", _min(0), _min(60)) for key in "ABC"],
        )

        self.assertFalse(result.conflict)
        self.assertEqual(result.clock, {"LASER1": 3600.0})
        for chave in "ABC":
            self.assertAlmostEqual(result.hm[chave], 20 * 60)

    def test_tempo_fisico_nao_dobra_com_duas_ops_em_producao(self):
        fisico = consolidate_physical_time([
            PhysicalInputSegment("LASER1", "Corte", EventCategory.PRODUCTION, _min(0), _min(60), "A"),
            PhysicalInputSegment("LASER1", "Corte", EventCategory.PRODUCTION, _min(0), _min(60), "B"),
        ])

        self.assertEqual(fisico["physical_seconds"], 3600)

    def test_so_a_producao_da_timeline_entra_no_rateio(self):
        # A produz 0-60; B produz 0-30 e fica parada 30-60. Parada não divide.
        def eventos(*itens):
            return [
                {"id": i, "estado": estado, "data_hora": _min(m)}
                for i, (estado, m) in enumerate(itens, 1)
            ]

        tl_a = build_operator_timeline(eventos(("producao", 0)), start=_min(0), end=_min(60))
        tl_b = build_operator_timeline(
            eventos(("producao", 0), ("parada", 30)), start=_min(0), end=_min(60)
        )
        result = allocate_by_badge(
            [("A", "LASER1", production_spans(tl_a)), ("B", "LASER1", production_spans(tl_b))],
            [("A", "C1", _min(0), None), ("B", "C1", _min(0), None)],
        )

        self.assertAlmostEqual(result.hm["B"], 15 * 60)
        self.assertAlmostEqual(result.hm["A"], 15 * 60 + 30 * 60)


if __name__ == "__main__":
    unittest.main()
