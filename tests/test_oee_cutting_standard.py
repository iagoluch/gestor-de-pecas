"""Performance do Corte pelo previsto do SigmaNEST (manufatura, 19/10/2026).

Regra: padrão do plano = tempo previsto do plano × (chapas cortadas ÷ chapas
do plano). Cada linha de ``apontamentos_corte`` é uma chapa física com o
próprio previsto. Números sintéticos.
"""

from __future__ import annotations

import unittest
from datetime import datetime

from mes.analytics.oee import FTT_RULE, calculate_oee
from mes.contracts import AnalyticsFilter
from mes.domain import DataAvailability, EventCategory
from mes.services.management import ManagementService
from tests.test_value_explanation import _BaseRepo

DIA = datetime(2026, 8, 19)
AGORA = datetime(2026, 8, 21, 12, 0)
LABEL = "Performance baseada no previsto do nesting"


def _sheet(id_, hora, *, previsto=600.0, status="Finalizado", tarefa="T-1"):
    inicio = datetime(2026, 8, 19, hora, 0)
    return {
        "apontamento_id": id_,
        "tarefa": tarefa,
        "programa": "P-1",
        "nesting": id_,
        "maquina": "LASER1",
        "inicio": inicio,
        "fim": inicio.replace(minute=15) if status == "Finalizado" else None,
        "previsto_segundos": previsto,
        "real_segundos": 900.0,
        "real_periodo_segundos": 900.0,
        "status": status,
    }


class _CutRepo(_BaseRepo):
    def __init__(self, nestings, cutting=None):
        super().__init__(cutting=cutting)
        self._nestings = nestings

    def listar_tempos_nesting_corte(self, **_k):
        return [dict(row) for row in self._nestings]


def _overview(repo):
    service = ManagementService(repo, now_func=lambda: AGORA)
    return service.get_overview(AnalyticsFilter(DIA, DIA.replace(hour=23, minute=59)))


def _corte(overview):
    return next(item for item in overview["sector_kpis"] if item["setor"] == "Corte")


class CuttingStandardTests(unittest.TestCase):
    def test_duas_de_quatro_chapas_cortadas_creditam_metade_do_previsto(self):
        # Plano de 4 chapas × 600 s = 2400 s previsto; só 2 cortadas no dia.
        overview = _overview(_CutRepo([_sheet(1, 8), _sheet(2, 9)]))
        corte = _corte(overview)

        self.assertEqual(corte["kpi_time_bases"]["standard_run_seconds"], 2400.0 * 2 / 4)
        self.assertEqual(corte["kpi_time_bases"]["worked_seconds"], 1800.0)
        performance = corte["metrics"]["performance"]
        self.assertEqual(performance["availability"], DataAvailability.AVAILABLE.value)
        self.assertAlmostEqual(performance["value"], 1200.0 / 1800.0 * 100.0)
        trace = corte["kpi_calculation"]
        self.assertEqual(trace["standard_origin"], "nesting_previsto")
        self.assertEqual(trace["performance_label"], LABEL)
        self.assertEqual(
            overview["kpi_calculation"]["cutting_standard"]["cut_sheets_with_standard"], 2
        )

    def test_chapa_em_processo_nao_credita_padrao(self):
        overview = _overview(_CutRepo([_sheet(1, 8), _sheet(2, 9, status="Em processo")]))

        self.assertEqual(_corte(overview)["kpi_time_bases"]["standard_run_seconds"], 600.0)

    def test_tarefa_concluida_com_previsto_nao_fica_sem_padrao(self):
        production = [{
            "codigo_tarefa": "T-1", "concluido_em": datetime(2026, 8, 19, 9, 15),
            "maquina": "LASER1", "codigo_op": "OP-9", "quantidade": 10,
        }]
        overview = _overview(_CutRepo([_sheet(1, 8), _sheet(2, 9)], cutting=production))
        corte = _corte(overview)

        self.assertEqual(corte["pecas_boas_sem_tempo_padrao"], 0)
        self.assertEqual(
            corte["metrics"]["performance"]["availability"], DataAvailability.AVAILABLE.value
        )

    def test_plano_sem_previsto_continua_sem_padrao(self):
        production = [{
            "codigo_tarefa": "T-1", "concluido_em": datetime(2026, 8, 19, 8, 15),
            "maquina": "LASER1", "codigo_op": "OP-9", "quantidade": 10,
        }]
        overview = _overview(_CutRepo([_sheet(1, 8, previsto=None)], cutting=production))
        corte = _corte(overview)

        self.assertEqual(corte["kpi_time_bases"]["standard_run_seconds"], 0.0)
        self.assertEqual(corte["pecas_boas_sem_tempo_padrao"], 10)
        self.assertEqual(
            corte["metrics"]["performance"]["availability"],
            DataAvailability.NOT_CONFIGURED.value,
        )
        self.assertNotIn("standard_origin", corte["kpi_calculation"])
        self.assertEqual(
            overview["kpi_calculation"]["cutting_standard"]["cut_sheets_without_standard"], 1
        )


class FttRuleTraceTests(unittest.TestCase):
    def test_ftt_rule_no_trace(self):
        calc = calculate_oee(
            seconds_by_category={EventCategory.PRODUCTION: 600.0},
            good_quantity=9, scrap_quantity=1, rework_quantity=0,
            standard_run_seconds=540.0,
        )
        rule = calc.trace_dict()["ftt_rule"]

        self.assertEqual(rule["decided_at"], "2026-10-19")
        self.assertEqual(
            set(rule["rules"]),
            {
                "a_retrabalho_fora_das_boas_de_primeira",
                "b_recuperacao_nao_soma_boa",
                "c_unidade_no_corte",
            },
        )
        # Cópia: alterar o trace não altera a regra publicada.
        rule["rules"].clear()
        self.assertEqual(len(FTT_RULE["rules"]), 3)


if __name__ == "__main__":
    unittest.main()
