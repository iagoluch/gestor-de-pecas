import unittest
from datetime import datetime, timedelta

from mes.analytics.oee import calculate_oee
from mes.contracts import AIRequestContext, AnalyticsFilter
from mes.domain import DataAvailability, EventCategory
from mes.services.ai_tools import AIToolRegistry
from mes.services.frontend_facade import FrontendBackendFacade
from tests.test_backend_canonical_v11 import _CanonicalRepo


class _ThreeDayOeeRepo(_CanonicalRepo):
    """Cenário mínimo cuja consulta respeita o período recebido."""

    @staticmethod
    def _overlaps(start, finish, inicio, fim):
        return start < fim and finish > inicio

    def listar_fatos_operacionais_periodo(self, inicio, fim, **_kwargs):
        rows = []
        for offset in range(3):
            start = datetime(2026, 8, 18 + offset, 8, 0)
            finish = start + timedelta(hours=1)
            if self._overlaps(start, finish, inicio, fim):
                rows.append({
                    "id": offset + 1,
                    "op": f"OP-{offset + 1}",
                    "tipo_setor": "Dobra",
                    "maquina": "DOBRA1",
                    "status": "Finalizado",
                    "data_inicio": start,
                    "data_fim": finish,
                    "quantidade_boa": 9,
                    "quantidade_refugo": 0,
                    "quantidade_retrabalho": 0,
                    "tempo_medio_segundos": 100,
                    "eventos": [
                        {"id": offset * 2 + 1, "estado": "producao", "data_hora": start},
                        {"id": offset * 2 + 2, "estado": "finalizado", "data_hora": finish},
                    ],
                })
        return rows

    def listar_estados_recurso_periodo(self, inicio, fim, **_kwargs):
        rows = []
        for offset in range(3):
            start = datetime(2026, 8, 18 + offset, 8, 0)
            finish = start + timedelta(hours=1)
            if self._overlaps(start, finish, inicio, fim):
                rows.append({
                    "id": offset + 1,
                    "recurso": "DOBRA1",
                    "tipo_setor": "Dobra",
                    "categoria": "producao",
                    "data_inicio": start,
                    "data_fim": finish,
                })
        return rows

    def listar_eventos_quantidade_periodo(self, inicio, fim, **_kwargs):
        return [
            {"tipo": "boa", "quantidade": 9, "tipo_setor": "Dobra"}
            for offset in range(3)
            if inicio <= datetime(2026, 8, 18 + offset, 8, 30) <= fim
        ]


class CanonicalOeeCalculationTests(unittest.TestCase):
    def test_formula_validada_preserva_componentes_unidade_e_precisao(self):
        calculation = calculate_oee(
            seconds_by_category={
                EventCategory.PRODUCTION: 3600,
                EventCategory.SETUP: 600,
                EventCategory.DOWNTIME: 600,
                EventCategory.QUEUE: 600,
                EventCategory.NO_DEMAND: 1800,
            },
            good_quantity=90,
            scrap_quantity=5,
            rework_quantity=5,
            standard_run_seconds=900,
        )

        # Base disponível = produção + setup + parada. Fila e ausência de
        # demanda ficam fora: recurso sem trabalho atribuído não é perda de
        # disponibilidade.
        self.assertAlmostEqual(calculation.availability.value, 4200 / 4800 * 100)
        self.assertAlmostEqual(calculation.performance.value, 1500 / 4200 * 100)
        self.assertAlmostEqual(calculation.ftt.value, 90.0)
        self.assertAlmostEqual(
            calculation.oee.value,
            4200 / 4800 * 1500 / 4200 * 0.9 * 100,
        )
        self.assertEqual(calculation.oee.unit, "%")
        self.assertEqual(calculation.oee.availability, DataAvailability.AVAILABLE)
        self.assertEqual(calculation.time_bases["performance_difference_seconds"], -2700.0)
        self.assertEqual(calculation.time_bases["available_seconds"], 4800.0)
        self.assertEqual(calculation.time_bases["no_demand_seconds"], 1800.0)
        self.assertEqual(calculation.time_bases["queue_seconds"], 600.0)

    def test_recurso_sem_demanda_nao_derruba_a_disponibilidade(self):
        """Regressão do resumo quinzenal: produção real com Disp. ≈ 0%.

        Duas semanas de recurso sem demanda com uma hora de produção davam
        Disponibilidade 0,1% e OEE 0% porque a ausência de demanda entrava na
        base disponível.
        """

        seconds_by_category = {
            EventCategory.PRODUCTION: 3600,
            EventCategory.NO_DEMAND: 14 * 9 * 3600,
        }
        calculation = calculate_oee(
            seconds_by_category=seconds_by_category,
            good_quantity=38,
            scrap_quantity=0,
            rework_quantity=0,
            standard_run_seconds=3600,
        )

        self.assertEqual(calculation.availability.value, 100.0)
        self.assertEqual(calculation.performance.value, 100.0)
        self.assertEqual(calculation.ftt.value, 100.0)
        self.assertEqual(calculation.oee.value, 100.0)

    def test_ausencia_real_de_dados_permanece_explicita(self):
        calculation = calculate_oee(
            seconds_by_category={},
            good_quantity=0,
            scrap_quantity=0,
            rework_quantity=0,
            standard_run_seconds=0,
        )

        self.assertIsNone(calculation.oee.value)
        self.assertEqual(calculation.oee.availability, DataAvailability.NO_RECORDS)
        self.assertIn("Disponibilidade", calculation.oee.reason)
        self.assertIn("FTT", calculation.oee.reason)


class OeeConsumerConsistencyTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 8, 19, 23, 59)
        self.filters = AnalyticsFilter(datetime(2026, 8, 19), self.now)
        self.facade = FrontendBackendFacade(_CanonicalRepo(), now_func=lambda: self.now)

    def test_dashboard_explicador_andon_relatorio_e_ia_recebem_o_mesmo_valor(self):
        overview = self.facade.inicio(self.filters)
        canonical = overview["kpis"]
        oee = canonical["oee"]

        self.assertAlmostEqual(oee["value"], 25.0)
        self.assertEqual(
            overview["kpi_time_bases"],
            self.facade.inicio(self.filters, include_insights=False)["kpi_time_bases"],
        )
        self.assertEqual(self.facade.analise("oee", self.filters)["value"], oee["value"])
        self.assertEqual(self.facade.analise("qualidade", self.filters)["ftt"], canonical["ftt"])
        self.assertEqual(self.facade.explain_kpi("oee", self.filters)["metric"], oee)
        self.assertEqual(self.facade.andon(self.filters)["summary"]["oee"], oee)
        self.assertEqual(
            self.facade.relatorio("gerencial", self.filters)["overview"]["kpis"],
            canonical,
        )
        self.assertEqual(
            self.facade.relatorio("indicadores", self.filters)["analytics"]["oee"]["value"],
            oee["value"],
        )

        registry = AIToolRegistry(self.facade, now_func=lambda: self.now)
        context = AIRequestContext(user_id=1, management_access=True, request_id="oee-consistency")
        ai_overview = registry.execute(
            "get_management_overview",
            {"inicio": "2026-08-19T00:00:00", "fim": "2026-08-19T23:59:00"},
            context,
        )
        ai_explanation = registry.execute(
            "explain_kpi",
            {
                "key": "oee",
                "inicio": "2026-08-19T00:00:00",
                "fim": "2026-08-19T23:59:00",
            },
            context,
        )
        self.assertEqual(ai_overview["data"]["kpis"]["oee"], oee)
        self.assertEqual(ai_explanation["data"]["metric"], oee)

    def test_modo_simulacao_muda_a_origem_dos_dados_mas_nao_a_formula(self):
        simulated = FrontendBackendFacade(
            _CanonicalRepo(),
            now_func=lambda: self.now,
            simulation_mode=True,
        ).inicio(self.filters, include_insights=False)
        normal = self.facade.inicio(self.filters, include_insights=False)

        self.assertEqual(simulated["kpis"], normal["kpis"])
        self.assertEqual(simulated["simulation"]["policy"], "canonical_oee")

    def test_oee_atual_nao_depende_da_serie_historica(self):
        payload = self.facade.analise("oee", self.filters)

        self.assertEqual(payload["availability"], DataAvailability.AVAILABLE.value)
        self.assertIsNotNone(payload["value"])
        self.assertEqual(len(payload["evolution"]["points"]), 1)
        self.assertEqual(payload["evolution"]["availability"], DataAvailability.INSUFFICIENT_DATA.value)

    def test_evolucao_consumindo_o_mesmo_calculo_canonico_por_periodo(self):
        filters = AnalyticsFilter(
            datetime(2026, 8, 18),
            datetime(2026, 8, 21),
        )
        facade = FrontendBackendFacade(
            _ThreeDayOeeRepo(),
            now_func=lambda: datetime(2026, 8, 21),
        )

        evolution = facade.analise("oee", filters)["evolution"]

        self.assertEqual(evolution["availability"], DataAvailability.AVAILABLE.value)
        self.assertEqual(evolution["total_buckets"], 3)
        self.assertEqual(evolution["available_points"], 3)
        self.assertEqual(evolution["calculation_policy"], "canonical_oee")
        self.assertEqual([point["value"] for point in evolution["points"]], [25.0, 25.0, 25.0])
        self.assertTrue(all(point["unit"] == "%" for point in evolution["points"]))
        self.assertEqual(
            set(evolution["points"][0]["components"]),
            {"oee", "availability", "performance", "ftt"},
        )
        self.assertEqual(evolution["points"][0]["components"]["oee"]["value"], 25.0)
        self.assertEqual(evolution["points"][0]["components"]["availability"]["value"], 100.0)
        self.assertEqual(evolution["points"][0]["components"]["performance"]["value"], 25.0)
        self.assertEqual(evolution["points"][0]["components"]["ftt"]["value"], 100.0)

    def test_evolucao_limita_quantidade_de_intervalos_sem_inventar_valor(self):
        filters = AnalyticsFilter(
            datetime(2025, 8, 20),
            datetime(2026, 8, 20),
        )
        evolution = FrontendBackendFacade(
            _CanonicalRepo(),
            now_func=lambda: datetime(2026, 8, 20),
        ).management.get_oee_evolution(filters)

        self.assertLessEqual(evolution["total_buckets"], 31)
        self.assertEqual(evolution["total_buckets"], evolution["available_points"] + evolution["missing_points"])

    def test_projecao_ia_do_explicador_preserva_kpi_e_limita_evidencias(self):
        class _LargeExplanationFacade:
            def explain_kpi(self, key, filters):
                return {
                    "key": key,
                    "label": "OEE",
                    "metric": {"value": 82.4, "unit": "%", "availability": "disponivel"},
                    "period": filters.to_dict(),
                    "components": [
                        {"key": "availability", "value": 90.0},
                        {"key": "performance", "value": 92.0},
                        {"key": "ftt", "value": 99.5},
                    ],
                    "causes": [{"cause": f"causa-{index}"} for index in range(9)],
                    "resources": [{"resource": f"R-{index}"} for index in range(9)],
                    "evidence": [
                        {"kind": ("parada", "tempo_padrao_x_real", "boa")[index % 3], "id": index}
                        for index in range(20)
                    ],
                    "calculation_policy": "backend_only",
                    "simulation_only": False,
                    "limitation": None,
                }

        registry = AIToolRegistry(_LargeExplanationFacade(), now_func=lambda: self.now)
        result = registry.execute(
            "explain_kpi",
            {"key": "oee"},
            AIRequestContext(user_id=1, management_access=True, request_id="compact-oee"),
        )

        self.assertEqual(result["data"]["metric"]["value"], 82.4)
        self.assertEqual(len(result["data"]["components"]), 3)
        self.assertEqual(len(result["data"]["evidence"]), 5)
        self.assertEqual(len(result["data"]["causes"]), 3)
        self.assertEqual(len(result["data"]["resources"]), 3)
        self.assertEqual(result["data"]["ai_projection"]["evidence"], {
            "total": 20,
            "returned": 5,
            "truncated": True,
        })
        self.assertTrue(result["limits"]["truncated"])

        component_result = registry.execute(
            "explain_kpi",
            {"key": "performance"},
            AIRequestContext(user_id=1, management_access=True, request_id="compact-component"),
        )
        self.assertEqual(component_result["data"]["metric"]["value"], 82.4)
        self.assertEqual(component_result["data"]["evidence"], [])
        self.assertEqual(component_result["data"]["ai_projection"]["evidence"], {
            "total": 20,
            "returned": 0,
            "truncated": True,
        })


if __name__ == "__main__":
    unittest.main()
