"""`merge_intervals` (mes/analytics/intervals.py) é a fonte única de união
de intervalos para calendário produtivo e consolidação de tempo físico —
o resultado vira segundos contabilizados em disponibilidade e OEE. Não
tinha nenhum teste dedicado antes desta rodada.
"""

from __future__ import annotations

from datetime import datetime
import unittest

from mes.analytics.intervals import merge_intervals


def _dt(hour, minute=0):
    return datetime(2026, 9, 23, hour, minute)


class MergeIntervalsTests(unittest.TestCase):
    def test_lista_vazia(self):
        self.assertEqual(merge_intervals([]), [])

    def test_intervalo_unico(self):
        self.assertEqual(
            merge_intervals([(_dt(8), _dt(10))]),
            [(_dt(8), _dt(10))],
        )

    def test_intervalos_disjuntos_permanecem_separados(self):
        resultado = merge_intervals([(_dt(8), _dt(9)), (_dt(10), _dt(11))])
        self.assertEqual(resultado, [(_dt(8), _dt(9)), (_dt(10), _dt(11))])

    def test_intervalos_sobrepostos_se_unem(self):
        resultado = merge_intervals([(_dt(8), _dt(10)), (_dt(9), _dt(12))])
        self.assertEqual(resultado, [(_dt(8), _dt(12))])

    def test_intervalos_adjacentes_tambem_se_unem(self):
        # fim de um == início do outro: mesmo segundo contado uma única vez.
        resultado = merge_intervals([(_dt(8), _dt(10)), (_dt(10), _dt(12))])
        self.assertEqual(resultado, [(_dt(8), _dt(12))])

    def test_intervalo_totalmente_contido_desaparece_no_maior(self):
        resultado = merge_intervals(
            [(_dt(8), _dt(12)), (_dt(9), _dt(10))]
        )
        self.assertEqual(resultado, [(_dt(8), _dt(12))])

    def test_entrada_fora_de_ordem_e_ordenada_no_resultado(self):
        resultado = merge_intervals(
            [(_dt(14), _dt(15)), (_dt(8), _dt(9)), (_dt(10), _dt(11))]
        )
        self.assertEqual(
            resultado, [(_dt(8), _dt(9)), (_dt(10), _dt(11)), (_dt(14), _dt(15))]
        )

    def test_intervalo_invertido_ou_de_duracao_zero_e_descartado(self):
        # fim <= início não representa tempo decorrido.
        resultado = merge_intervals([(_dt(10), _dt(8)), (_dt(9), _dt(9))])
        self.assertEqual(resultado, [])

    def test_intervalo_invalido_nao_atrapalha_os_validos(self):
        resultado = merge_intervals(
            [(_dt(8), _dt(9)), (_dt(11), _dt(10)), (_dt(12), _dt(13))]
        )
        self.assertEqual(resultado, [(_dt(8), _dt(9)), (_dt(12), _dt(13))])

    def test_tres_intervalos_encadeados_viram_um_so(self):
        resultado = merge_intervals(
            [(_dt(8), _dt(9)), (_dt(9), _dt(10)), (_dt(10), _dt(11))]
        )
        self.assertEqual(resultado, [(_dt(8), _dt(11))])


if __name__ == "__main__":
    unittest.main()
