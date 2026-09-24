"""Recurso sem demanda: bucket próprio, fora da base do OEE.

Cenário reproduzido do relato de campo: no retorno do turno o scheduler
encerra o ``fora_turno`` e grava uma ``fila`` marcada com
``retorno_turno_sem_demanda``. Antes da correção esse tempo (a) entrava na
base disponível do OEE e derrubava a Disponibilidade para ~0% mesmo com
produção real registrada e (b) não tinha coluna no rollup por setor, então
sumia da planilha enquanto "fora de turno" ficava sendo o único balde grande.
"""

from datetime import datetime
import unittest

from mes.analytics.resource_state import physical_state_category
from mes.contracts import AnalyticsFilter
from mes.domain import EventCategory, ManufacturingRules, SHIFT_START_NO_DEMAND_TYPE
from mes.services.frontend_facade import FrontendBackendFacade
from mes.services.management import ManagementService
from tests.test_backend_canonical_v11 import _CanonicalRepo


DIA = datetime(2026, 9, 17)


class _ShiftReturnRepo(_CanonicalRepo):
    """Um dia real: noite fora de turno, 1h de produção e o resto sem demanda."""

    def listar_fatos_operacionais_periodo(self, *_args, **_kwargs):
        # Existe apontamento real no período: é dele que sai o tempo padrão da
        # Performance. As quantidades vêm de ``eventos_quantidade_producao``.
        return [{
            "id": 1,
            "op": "OP1",
            "tipo_setor": "Dobra",
            "maquina": "DOBRA1",
            "status": "Finalizado",
            "data_inicio": datetime(2026, 9, 17, 8, 0),
            "data_fim": datetime(2026, 9, 17, 9, 0),
            "quantidade_boa": 38,
            "quantidade_refugo": 0,
            "quantidade_retrabalho": 0,
            "tempo_medio_segundos": 90,
            "eventos": [
                {"id": 1, "estado": "producao", "data_hora": datetime(2026, 9, 17, 8, 0)},
                {"id": 2, "estado": "finalizado", "data_hora": datetime(2026, 9, 17, 9, 0)},
            ],
        }]

    def listar_estados_recurso_periodo(self, *_args, categoria=None, **_kwargs):
        rows = [
            {
                "id": 1,
                "recurso": "DOBRA1",
                "tipo_setor": "Dobra",
                "categoria": "fora_turno",
                "data_inicio": datetime(2026, 9, 16, 17, 30),
                "data_fim": datetime(2026, 9, 17, 8, 0),
                "automatico": True,
                "planejado": True,
                "tipo_interrupcao": "fim_turno",
            },
            {
                "id": 2,
                "recurso": "DOBRA1",
                "tipo_setor": "Dobra",
                "categoria": "producao",
                "data_inicio": datetime(2026, 9, 17, 8, 0),
                "data_fim": datetime(2026, 9, 17, 9, 0),
            },
            {
                "id": 3,
                "recurso": "DOBRA1",
                "tipo_setor": "Dobra",
                "categoria": "fila",
                "data_inicio": datetime(2026, 9, 17, 9, 0),
                "data_fim": datetime(2026, 9, 17, 17, 30),
                "automatico": True,
                "motivo": "Retorno do turno — recurso sem demanda",
                "tipo_interrupcao": SHIFT_START_NO_DEMAND_TYPE,
            },
        ]
        if categoria:
            rows = [row for row in rows if row["categoria"] == categoria]
        return rows

    def listar_eventos_quantidade_periodo(self, *_args, **_kwargs):
        return [{"tipo": "boa", "quantidade": 38, "tipo_setor": "Dobra", "recurso": "DOBRA1"}]


class NoDemandCategoryTests(unittest.TestCase):
    def test_fila_do_retorno_de_turno_vira_sem_demanda(self):
        self.assertIs(
            physical_state_category(
                {"categoria": "fila", "tipo_interrupcao": SHIFT_START_NO_DEMAND_TYPE}
            ),
            EventCategory.NO_DEMAND,
        )

    def test_fila_sem_op_vira_sem_demanda_independentemente_da_origem(self):
        self.assertIs(
            physical_state_category({"categoria": "fila"}),
            EventCategory.NO_DEMAND,
        )

    def test_fila_vinculada_a_op_nao_e_reclassificada(self):
        self.assertIs(
            physical_state_category({"categoria": "fila", "op": "OP-123"}),
            EventCategory.QUEUE,
        )

    def test_fora_de_turno_nunca_e_absorvido_pela_ausencia_de_demanda(self):
        self.assertIs(
            physical_state_category(
                {"categoria": "fora_turno", "tipo_interrupcao": "fim_turno"}
            ),
            EventCategory.OUT_OF_SHIFT,
        )

    def test_sem_demanda_nao_e_produtivo(self):
        self.assertFalse(ManufacturingRules.is_productive(EventCategory.NO_DEMAND))

    def test_regra_de_ausencia_de_demanda_tem_fonte_unica(self):
        self.assertTrue(
            ManufacturingRules.state_is_no_demand(
                category=EventCategory.QUEUE, interruption_type=SHIFT_START_NO_DEMAND_TYPE
            )
        )
        self.assertTrue(
            ManufacturingRules.state_is_no_demand(category=EventCategory.QUEUE)
        )
        self.assertFalse(
            ManufacturingRules.state_is_no_demand(
                category=EventCategory.QUEUE, operation="OP-123"
            )
        )


class NoDemandRollupTests(unittest.TestCase):
    def setUp(self):
        self.filters = AnalyticsFilter(DIA, datetime(2026, 9, 17, 23, 59))
        self.overview = ManagementService(_ShiftReturnRepo()).get_overview(self.filters)

    def test_tempo_sem_demanda_tem_bucket_proprio_no_setor(self):
        setor = next(row for row in self.overview["sectors"] if row["setor"] == "Dobra")

        self.assertAlmostEqual(setor["tempo_sem_demanda_segundos"], 8.5 * 3600)
        self.assertAlmostEqual(setor["tempo_fora_turno_segundos"], 8 * 3600)
        self.assertEqual(setor["tempo_fila_segundos"], 0.0)
        self.assertAlmostEqual(setor["tempo_producao_segundos"], 3600)

    def test_horas_publicam_ausencia_de_demanda_separada_de_fora_de_turno(self):
        horas = self.overview["hours"]

        self.assertAlmostEqual(horas["no_demand_seconds"], 8.5 * 3600)
        self.assertAlmostEqual(horas["out_of_shift_seconds"], 8 * 3600)
        self.assertEqual(horas["queue_seconds"], 0.0)

    def test_sem_demanda_mantem_disponibilidade_e_entra_na_performance(self):

        kpis = self.overview["kpis"]

        self.assertEqual(kpis["availability"]["value"], 100.0)
        self.assertEqual(kpis["ftt"]["value"], 100.0)
        base_performance = 3600 + 8.5 * 3600
        self.assertAlmostEqual(kpis["performance"]["value"], 90 * 38 / base_performance * 100)
        self.assertAlmostEqual(kpis["oee"]["value"], 90 * 38 / base_performance * 100)
        self.assertEqual(self.overview["production"]["good"], 38)

    def test_composicao_do_tempo_nomeia_a_ausencia_de_demanda(self):
        facade = FrontendBackendFacade(_ShiftReturnRepo(), now_func=lambda: datetime(2026, 9, 17, 23, 59))
        itens = {
            item["label"]: item["seconds"]
            for item in facade.inicio(self.filters, include_insights=False)["time_composition"]["items"]
        }

        self.assertAlmostEqual(itens["Recurso sem demanda"], 8.5 * 3600)
        self.assertAlmostEqual(itens["Fora do turno"], 8 * 3600)
        self.assertNotIn("Fila / espera", itens)


if __name__ == "__main__":
    unittest.main()
