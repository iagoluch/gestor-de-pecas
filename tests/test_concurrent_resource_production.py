"""OPs simultâneas no mesmo recurso: regra de ocupação e divisão do tempo.

Decisão do usuário (01/10/2026). A estratégia de rateio igualitária é
provisória (não confirmada); os testes fixam a conservação do tempo físico,
que vale para qualquer estratégia.
"""

from datetime import datetime, timedelta
import unittest

from mes.analytics.physical_time import PhysicalInputSegment, consolidate_physical_time
from mes.analytics.rateio import (
    canonical_resource_key,
    split_concurrent_production,
    split_concurrent_time,
)
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

    def test_setup_e_retrabalho_continuam_exclusivos(self):
        self.assertTrue(resource_concurrency_conflict(self.P, self.R, ["Em processo"]))
        self.assertTrue(resource_concurrency_conflict(self.P, OperatorState.REWORK, ["Em processo"]))
        self.assertTrue(resource_concurrency_conflict(self.Q, self.P, ["Setup"]))
        self.assertTrue(resource_concurrency_conflict(self.Q, self.P, ["Em processo", "Retrabalho"]))
        self.assertTrue(resource_concurrency_conflict(self.S, self.P, ["Setup"]))

    def test_parada_direto_da_fila_nao_contorna_a_trava(self):
        self.assertTrue(resource_concurrency_conflict(self.Q, self.S, ["Em processo"]))


class DivisaoDoTempoTests(unittest.TestCase):
    def test_duas_ops_com_sobreposicao_parcial_dividem_so_o_trecho_comum(self):
        # A: 0-60, B: 30-90 no mesmo recurso. Físico = 90 min.
        result = split_concurrent_time([
            ("A", "LASER1", [(_min(0), _min(60))]),
            ("B", "LASER1", [(_min(30), _min(90))]),
        ])

        self.assertAlmostEqual(result["A"], 30 * 60 + 15 * 60)
        self.assertAlmostEqual(result["B"], 15 * 60 + 30 * 60)
        self.assertAlmostEqual(sum(result.values()), 90 * 60)

    def test_tres_ops_dividem_por_tres_no_trecho_comum(self):
        # A: 0-60, B: 0-30, C: 0-30 -> 0-30 dividido por 3, 30-60 só A.
        result = split_concurrent_time([
            ("A", "LASER1", [(_min(0), _min(60))]),
            ("B", "LASER1", [(_min(0), _min(30))]),
            ("C", "LASER1", [(_min(0), _min(30))]),
        ])

        self.assertAlmostEqual(result["B"], 10 * 60)
        self.assertAlmostEqual(result["C"], 10 * 60)
        self.assertAlmostEqual(result["A"], 10 * 60 + 30 * 60)
        self.assertAlmostEqual(sum(result.values()), 60 * 60)

    def test_alias_codigo_e_caixa_do_mesmo_posto_dividem_o_tempo(self):
        # M2: o agrupamento e o arredondamento por recurso usam a mesma chave.
        self.assertEqual(canonical_resource_key("Laser Ensis 3015"), "LASER1")
        self.assertEqual(canonical_resource_key("laser1"), "LASER1")
        result = split_concurrent_time([
            ("A", "LASER1", [(_min(0), _min(60))]),
            ("B", "Laser Ensis 3015", [(_min(0), _min(60))]),
            ("C", "laser1", [(_min(0), _min(60))]),
        ])

        self.assertAlmostEqual(sum(result.values()), 60 * 60)
        for chave in "ABC":
            self.assertAlmostEqual(result[chave], 20 * 60)

    def test_recursos_diferentes_nao_dividem_entre_si(self):
        result = split_concurrent_time([
            ("A", "LASER1", [(_min(0), _min(60))]),
            ("B", "DOBRA3", [(_min(0), _min(60))]),
        ])

        self.assertAlmostEqual(result["A"], 3600)
        self.assertAlmostEqual(result["B"], 3600)

    def test_op_sozinha_recebe_o_tempo_inteiro_e_intervalos_vazios_sao_ignorados(self):
        result = split_concurrent_time([
            ("A", "LASER1", [(_min(0), _min(10)), (_min(20), _min(20))]),
        ])

        self.assertEqual(result, {"A": 600.0})

    def test_soma_por_op_nunca_passa_do_tempo_fisico_da_uniao(self):
        entradas = [
            ("A", "LASER1", [(_min(0), _min(45))]),
            ("B", "LASER1", [(_min(10), _min(70))]),
            ("C", "LASER1", [(_min(40), _min(100)), (_min(120), _min(130))]),
        ]
        dividido = split_concurrent_time(entradas)

        fisico = consolidate_physical_time([
            PhysicalInputSegment("LASER1", "Corte", EventCategory.PRODUCTION, ini, fim, key)
            for key, _, spans in entradas for ini, fim in spans
        ])
        self.assertLessEqual(sum(dividido.values()), fisico["physical_seconds"] + 0.001)
        self.assertAlmostEqual(sum(dividido.values()), (100 + 10) * 60)

    def test_tempo_fisico_nao_dobra_com_duas_ops_em_producao(self):
        fisico = consolidate_physical_time([
            PhysicalInputSegment("LASER1", "Corte", EventCategory.PRODUCTION, _min(0), _min(60), "A"),
            PhysicalInputSegment("LASER1", "Corte", EventCategory.PRODUCTION, _min(0), _min(60), "B"),
        ])

        self.assertEqual(fisico["physical_seconds"], 3600)

    def test_so_a_producao_e_dividida_na_timeline_da_op(self):
        # A produz 0-60; B produz 0-30 e fica parada 30-60. Parada não divide.
        def eventos(*itens):
            return [
                {"id": i, "estado": estado, "data_hora": _min(m)}
                for i, (estado, m) in enumerate(itens, 1)
            ]

        tl_a = build_operator_timeline(
            eventos(("producao", 0)), start=_min(0), end=_min(60)
        )
        tl_b = build_operator_timeline(
            eventos(("producao", 0), ("parada", 30)), start=_min(0), end=_min(60)
        )
        result = split_concurrent_production([
            ("A", "LASER1", tl_a), ("B", "LASER1", tl_b),
        ])

        self.assertAlmostEqual(result["B"], 15 * 60)
        self.assertAlmostEqual(result["A"], 15 * 60 + 30 * 60)


class RateioPorSegmentoTests(unittest.TestCase):
    """Decisão do usuário: igualitário pelo número de OPs apontadas em cada
    instante. Cada trecho com N OPs simultâneas dá 1/N a cada uma; nunca se
    divide o total da OP pelo número de OPs."""

    def test_duas_ops_sobrepostas_inteiramente_dividem_50_50(self):
        result = split_concurrent_time([
            ("A", "LASER1", [(_min(0), _min(120))]),
            ("B", "LASER1", [(_min(0), _min(120))]),
        ])

        self.assertAlmostEqual(result["A"], 3600)
        self.assertAlmostEqual(result["B"], 3600)
        self.assertAlmostEqual(sum(result.values()), 2 * 3600)

    def test_op_b_entra_no_meio_de_a_divide_so_a_ultima_hora(self):
        # A 08:00-10:00; B 09:00-10:00. 08-09 só A (100%); 09-10 meio a meio.
        result = split_concurrent_time([
            ("A", "LASER1", [(_min(0), _min(120))]),
            ("B", "LASER1", [(_min(60), _min(120))]),
        ])

        self.assertAlmostEqual(result["A"], 90 * 60)
        self.assertAlmostEqual(result["B"], 30 * 60)
        self.assertAlmostEqual(sum(result.values()), 2 * 3600)

    def test_tres_ops_entrando_e_saindo_em_momentos_diferentes(self):
        # A 0-120; B 30-90; C 60-150. Segmentos elementares:
        #  0-30  A            -> A 30
        # 30-60  A,B          -> A 15, B 15
        # 60-90  A,B,C        -> 10 cada
        # 90-120 A,C          -> A 15, C 15
        # 120-150 C           -> C 30
        result = split_concurrent_time([
            ("A", "LASER1", [(_min(0), _min(120))]),
            ("B", "LASER1", [(_min(30), _min(90))]),
            ("C", "LASER1", [(_min(60), _min(150))]),
        ])

        self.assertAlmostEqual(result["A"], (30 + 15 + 10 + 15) * 60)
        self.assertAlmostEqual(result["B"], (15 + 10) * 60)
        self.assertAlmostEqual(result["C"], (10 + 15 + 30) * 60)
        self.assertAlmostEqual(sum(result.values()), 150 * 60)

    def test_segmento_com_uma_unica_op_recebe_100_por_cento(self):
        # B não toca o trecho 0-30 nem 90-120: A fica com eles inteiros.
        result = split_concurrent_time([
            ("A", "LASER1", [(_min(0), _min(120))]),
            ("B", "LASER1", [(_min(30), _min(90))]),
        ])

        self.assertAlmostEqual(result["B"], 30 * 60)
        self.assertAlmostEqual(result["A"], (30 + 30 + 30) * 60)
        self.assertAlmostEqual(sum(result.values()), 120 * 60)

    def test_divisao_e_por_segmento_e_nao_pelo_total_da_op(self):
        # Contra-prova: se dividisse o total da OP por N, A (120 min, N=2)
        # ficaria com 60 e B (30 min) com 15; a soma (75) não fecharia com o
        # tempo físico (120).
        result = split_concurrent_time([
            ("A", "LASER1", [(_min(0), _min(120))]),
            ("B", "LASER1", [(_min(90), _min(120))]),
        ])

        self.assertNotAlmostEqual(result["A"], 60 * 60)
        self.assertAlmostEqual(result["A"], (90 + 15) * 60)
        self.assertAlmostEqual(result["B"], 15 * 60)
        self.assertAlmostEqual(sum(result.values()), 120 * 60)


if __name__ == "__main__":
    unittest.main()
