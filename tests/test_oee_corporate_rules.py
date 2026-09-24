"""Cenários corporativos do OEE (PROMPT_OEE rev. 01, seção 13.1 e 13.2).

Os números são sintéticos e reproduzem a metodologia corporativa vigente;
passar aqui prova reprodução da regra, não equivalência ao OEE convencional.
"""

import math
import unittest

from mes.analytics.oee import (
    PERFORMANCE_ABOVE_LIMIT_ALERT,
    RESULT_ORIGIN_FORMULA,
    RESULT_ORIGIN_NO_DEMAND,
    calculate_oee,
)
from mes.domain import DataAvailability, EventCategory

MIN = 60.0
TOLERANCE = 1e-9


def _oee(seconds, *, good=0, scrap=0, rework=0, standard=0.0, without_standard=0):
    return calculate_oee(
        seconds_by_category=seconds,
        good_quantity=good,
        scrap_quantity=scrap,
        rework_quantity=rework,
        standard_run_seconds=standard,
        good_without_standard_quantity=without_standard,
    )


class CorporateScenarioTests(unittest.TestCase):
    def test_c03_padrao_de_1_minuto_com_refugo(self):
        calc = _oee({EventCategory.PRODUCTION: 100 * MIN}, good=90, scrap=10, standard=90 * MIN)

        self.assertAlmostEqual(calc.availability.value, 100.0, delta=TOLERANCE)
        self.assertAlmostEqual(calc.performance.value, 90.0, delta=TOLERANCE)
        self.assertAlmostEqual(calc.ftt.value, 90.0, delta=TOLERANCE)
        self.assertAlmostEqual(calc.oee.value, 81.0, delta=TOLERANCE)
        self.assertEqual(calc.result_origin, RESULT_ORIGIN_FORMULA)

    def test_c04_setup_como_credito_de_apoio(self):
        calc = _oee(
            {
                EventCategory.PRODUCTION: 360 * MIN,
                EventCategory.SETUP: 60 * MIN,
                EventCategory.DOWNTIME: 60 * MIN,
            },
            good=300,
            standard=300 * MIN,
        )

        self.assertEqual(calc.time_bases["worked_seconds"], 420 * MIN)
        self.assertAlmostEqual(calc.availability.value, 87.5, delta=TOLERANCE)
        self.assertAlmostEqual(calc.performance.value, 85.7142857142857, delta=1e-7)
        self.assertAlmostEqual(calc.ftt.value, 100.0, delta=TOLERANCE)
        self.assertAlmostEqual(calc.oee.value, 75.0, delta=TOLERANCE)

    def test_c05_ftt_com_entradas_mutuamente_exclusivas(self):
        calc = _oee({EventCategory.PRODUCTION: 100 * MIN}, good=85, scrap=5, rework=10, standard=85 * MIN)

        self.assertAlmostEqual(calc.ftt.value, 85.0, delta=TOLERANCE)

    def test_c06_periodo_integralmente_sem_demanda_aplica_excecao_explicita(self):
        calc = _oee({
            EventCategory.NO_DEMAND: 480 * MIN,
            EventCategory.OUT_OF_SHIFT: 16 * 60 * MIN,
        })

        self.assertEqual(calc.availability.value, 100.0)
        self.assertEqual(calc.performance.value, 0.0)
        self.assertIsNone(calc.ftt.value)
        self.assertEqual(calc.ftt.availability, DataAvailability.NOT_APPLICABLE)
        self.assertEqual(calc.oee.value, 0.0)
        self.assertEqual(calc.oee.availability, DataAvailability.AVAILABLE)
        self.assertEqual(calc.result_origin, RESULT_ORIGIN_NO_DEMAND)
        self.assertIn("integralmente sem demanda", calc.oee.reason)
        self.assertEqual(calc.time_bases["no_demand_seconds"], 480 * MIN)
        self.assertEqual(calc.trace_dict()["result_origin"], RESULT_ORIGIN_NO_DEMAND)

    def test_c07_apenas_fora_de_turno_nao_fabrica_disponibilidade(self):
        calc = _oee({EventCategory.OUT_OF_SHIFT: 24 * 60 * MIN})

        self.assertIsNone(calc.availability.value)
        self.assertIsNone(calc.oee.value)
        self.assertEqual(calc.result_origin, RESULT_ORIGIN_FORMULA)

    def test_c08_sem_demanda_em_periodo_misto_nao_altera_os_fatores(self):
        base_seconds = {
            EventCategory.PRODUCTION: 360 * MIN,
            EventCategory.SETUP: 60 * MIN,
            EventCategory.DOWNTIME: 60 * MIN,
        }
        base = _oee(base_seconds, good=300, standard=300 * MIN)
        mixed = _oee(
            {**base_seconds, EventCategory.NO_DEMAND: 5 * 60 * MIN},
            good=300,
            standard=300 * MIN,
        )

        for factor in ("availability", "performance", "ftt", "oee"):
            self.assertAlmostEqual(
                getattr(mixed, factor).value, getattr(base, factor).value, delta=TOLERANCE
            )
        self.assertEqual(mixed.time_bases["no_demand_seconds"], 5 * 60 * MIN)
        self.assertEqual(mixed.result_origin, RESULT_ORIGIN_FORMULA)

    def test_c11_sem_quantidade_nao_preenche_ftt_nem_zera_oee(self):
        calc = _oee({EventCategory.PRODUCTION: 60 * MIN})

        self.assertIsNone(calc.ftt.value)
        self.assertIsNone(calc.oee.value)
        self.assertEqual(calc.oee.availability, DataAvailability.INSUFFICIENT_DATA)

    def test_sem_demanda_com_lacuna_de_dados_nao_vira_excecao(self):
        calc = _oee({EventCategory.NO_DEMAND: 420 * MIN, EventCategory.UNKNOWN: 60 * MIN})

        self.assertEqual(calc.result_origin, RESULT_ORIGIN_FORMULA)
        self.assertEqual(calc.availability.value, 0.0)
        self.assertIsNone(calc.oee.value)

    def test_sem_demanda_com_fila_de_op_ou_quantidade_nao_vira_excecao(self):
        with_queue = _oee({EventCategory.NO_DEMAND: 420 * MIN, EventCategory.QUEUE: 60 * MIN})
        with_quantity = _oee({EventCategory.NO_DEMAND: 480 * MIN}, good=5)

        self.assertEqual(with_queue.result_origin, RESULT_ORIGIN_FORMULA)
        self.assertEqual(with_quantity.result_origin, RESULT_ORIGIN_FORMULA)
        self.assertIsNone(with_queue.oee.value)
        self.assertIsNone(with_quantity.oee.value)


class StandardTimeAndIntegrityTests(unittest.TestCase):
    def test_tempo_padrao_ausente_bloqueia_performance_sem_fabricar_zero(self):
        calc = _oee({EventCategory.PRODUCTION: 60 * MIN}, good=40, without_standard=40)

        self.assertIsNone(calc.performance.value)
        self.assertEqual(calc.performance.availability, DataAvailability.NOT_CONFIGURED)
        self.assertIn("Tempo padrão ausente", calc.performance.reason)
        self.assertIsNone(calc.oee.value)
        self.assertAlmostEqual(calc.availability.value, 100.0, delta=TOLERANCE)

    def test_tempo_padrao_parcial_marca_performance_e_oee_como_parciais(self):
        calc = _oee(
            {EventCategory.PRODUCTION: 60 * MIN},
            good=40,
            standard=30 * MIN,
            without_standard=10,
        )

        self.assertAlmostEqual(calc.performance.value, 50.0, delta=TOLERANCE)
        self.assertEqual(calc.performance.availability, DataAvailability.PARTIAL)
        self.assertIn("10 de 40", calc.performance.reason)
        self.assertEqual(calc.oee.availability, DataAvailability.PARTIAL)
        self.assertAlmostEqual(calc.oee.value, 50.0, delta=TOLERANCE)

    def test_i06_performance_acima_de_100_preserva_valor_bruto_com_alerta(self):
        calc = _oee({EventCategory.PRODUCTION: 60 * MIN}, good=90, standard=90 * MIN)

        self.assertAlmostEqual(calc.performance.value, 150.0, delta=TOLERANCE)
        self.assertEqual(calc.alerts, (PERFORMANCE_ABOVE_LIMIT_ALERT,))
        self.assertIn("acima de 100%", calc.performance.reason)
        self.assertAlmostEqual(calc.oee.value, 150.0, delta=TOLERANCE)

    def test_nenhum_resultado_retorna_nan_ou_infinito(self):
        for seconds in ({}, {EventCategory.OUT_OF_SHIFT: 1.0}, {EventCategory.NO_DEMAND: 1.0}):
            calc = _oee(seconds)
            for metric in (calc.availability, calc.performance, calc.ftt, calc.oee):
                if metric.value is not None:
                    self.assertTrue(math.isfinite(metric.value))


if __name__ == "__main__":
    unittest.main()
