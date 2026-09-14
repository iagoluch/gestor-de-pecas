import unittest
from datetime import datetime

from mes.contracts import AnalyticsFilter
from mes.services.frontend_facade import FrontendBackendFacade


class _InsightsRepository:
    def __init__(self, *, with_targets=False):
        self.with_targets = with_targets
        self.calls = {
            "facts": 0,
            "states": 0,
            "quantities": 0,
            "rateios": 0,
            "targets": 0,
        }
        self.received_filters = []

    def listar_fatos_operacionais_periodo(self, inicio, fim, **filters):
        self.calls["facts"] += 1
        self.received_filters.append(("facts", filters))
        return [{
            "id": 101,
            "op": "OP-EXPLICAVEL",
            "numero_operacao": "20",
            "produto_codigo": "P-01",
            "tipo_setor": "Dobra",
            "codigo_recurso": "1303",
            "maquina": "1303",
            "data_inicio": datetime(2026, 8, 24, 8, 0),
            "data_fim": None,
            "status": "Em processo",
            "quantidade": 100,
            "quantidade_planejada_pcp": 100,
            "quantidade_boa": 60,
            "quantidade_refugo": 3,
            "quantidade_retrabalho": 2,
            "tempo_medio_segundos": 60,
            "eventos": [],
        }]

    def listar_estados_recurso_periodo(self, inicio, fim, categoria=None, **filters):
        self.calls["states"] += 1
        self.received_filters.append(("states", filters))
        rows = [
            {
                "id": 501,
                "evento_apontamento_id": 701,
                "apontamento_id": 101,
                "op": "OP-EXPLICAVEL",
                "numero_operacao": "20",
                "produto_codigo": "P-01",
                "recurso": "1303",
                "tipo_setor": "Dobra",
                "categoria": "producao",
                "data_inicio": datetime(2026, 8, 24, 8, 0),
                "data_fim": datetime(2026, 8, 24, 10, 0),
                "motivo": "Produção",
                "planejado": False,
                "automatico": False,
            },
            {
                "id": 502,
                "evento_apontamento_id": 702,
                "apontamento_id": 101,
                "op": "OP-EXPLICAVEL",
                "numero_operacao": "20",
                "produto_codigo": "P-01",
                "recurso": "1303",
                "tipo_setor": "Dobra",
                "categoria": "parada",
                "data_inicio": datetime(2026, 8, 24, 10, 0),
                "data_fim": None,
                "motivo": "Falta de material",
                "planejado": False,
                "automatico": False,
            },
        ]
        return [item for item in rows if categoria is None or item["categoria"] == categoria]

    def listar_eventos_quantidade_periodo(self, inicio, fim, **filters):
        self.calls["quantities"] += 1
        self.received_filters.append(("quantities", filters))
        base = {
            "data_hora": datetime(2026, 8, 24, 9, 30),
            "tipo_setor": "Dobra",
            "recurso": "1303",
            "op": "OP-EXPLICAVEL",
            "numero_operacao": "20",
            "produto_codigo": "P-01",
        }
        return [
            {**base, "id": 801, "tipo": "boa", "quantidade": 60},
            {**base, "id": 802, "tipo": "refugo", "quantidade": 3, "motivo": "Dimensional"},
            {**base, "id": 803, "tipo": "retrabalho", "quantidade": 2, "motivo": "Dobra incompleta"},
        ]

    def listar_rateios_tempo_periodo(self, inicio, fim, **filters):
        self.calls["rateios"] += 1
        self.received_filters.append(("rateios", filters))
        return [{
            "segundos_fisicos_periodo": 7200,
            "rateios": [{
                "op": "OP-EXPLICAVEL",
                "numero_operacao": "20",
                "segundos_atribuidos_periodo": 7200,
            }],
        }]

    def listar_tempos_nesting_corte(self, **_filters):
        return []

    def possui_calendario_produtivo(self, _setor, _recurso):
        return True

    def listar_inconsistencias_dados(self, **_filters):
        return []

    def listar_metas_indicadores(self, **filters):
        if not self.with_targets:
            raise AssertionError("Fonte de metas não deveria ter sido instalada neste cenário.")
        self.calls["targets"] += 1
        self.received_filters.append(("targets", filters))
        return [{
            "id": 901,
            "kpi": "oee",
            "meta": 80.0,
            "setor": "Dobra",
            "recurso": "1303",
            "source": "metas_indicadores_teste",
        }]


class _NoTargetInsightsRepository(_InsightsRepository):
    listar_metas_indicadores = None


class ManagementInsightsTests(unittest.TestCase):
    def setUp(self):
        self.filters = AnalyticsFilter(
            datetime(2026, 8, 24, 8, 0),
            datetime(2026, 8, 24, 12, 0),
            setor="Dobra",
            recurso="1303",
        )

    def _facade(self, repository):
        return FrontendBackendFacade(
            repository,
            now_func=lambda: datetime(2026, 8, 24, 12, 0),
        )

    def test_explicacoes_cobrem_os_quatro_kpis_com_componentes_e_evidencias(self):
        payload = self._facade(_NoTargetInsightsRepository()).insights(self.filters)

        self.assertEqual(
            set(payload["kpi_explanations"]),
            {"oee", "availability", "performance", "ftt"},
        )
        availability = payload["kpi_explanations"]["availability"]
        self.assertEqual(availability["largest_impact"]["cause"], "Falta de material")
        self.assertEqual(availability["largest_impact"]["impact_value"], 7200)
        self.assertEqual(availability["evidence"][0]["source_id"], "502")

        performance = payload["kpi_explanations"]["performance"]
        self.assertEqual(performance["largest_impact"]["op"], "OP-EXPLICAVEL")
        self.assertEqual(performance["largest_impact"]["impact_value"], 3600)
        self.assertEqual(performance["evidence"][0]["details"]["standard_seconds"], 3600)
        overview = self._facade(_NoTargetInsightsRepository()).inicio(
            self.filters,
            include_insights=False,
        )
        component_by_key = {item["key"]: item for item in performance["components"]}
        self.assertEqual(
            component_by_key["productive_net"]["value"],
            overview["kpi_time_bases"]["productive_net_seconds"],
        )
        self.assertEqual(
            component_by_key["worked"]["value"],
            overview["kpi_time_bases"]["worked_seconds"],
        )
        self.assertEqual(component_by_key["productive_net"]["formula_role"], "numerador")
        self.assertEqual(component_by_key["worked"]["formula_role"], "denominador")
        self.assertEqual(
            component_by_key["performance_difference"]["value"],
            overview["kpi_time_bases"]["performance_difference_seconds"],
        )

        ftt = payload["kpi_explanations"]["ftt"]
        self.assertEqual([item["value"] for item in ftt["components"]], [60, 3, 2])
        self.assertEqual(ftt["largest_impact"]["cause"], "Dimensional")
        self.assertEqual({item["source_id"] for item in ftt["evidence"]}, {"801", "802", "803"})

    def test_excecoes_usam_fatos_diretos_e_nao_inferem_atraso_da_op(self):
        payload = self._facade(_NoTargetInsightsRepository()).insights(self.filters)
        types = [item["type"] for item in payload["exceptions"]]

        self.assertEqual(types[0], "current_unplanned_downtime")
        self.assertIn("physical_downtime_in_period", types)
        self.assertIn("actual_time_above_standard", types)
        self.assertNotIn("configured_kpi_target", types)
        self.assertNotIn("op_below_plan", types)
        self.assertEqual(payload["critical_resources"][0]["impact_value"], 7200)
        self.assertEqual(payload["losses"][0]["cause"], "Falta de material")
        self.assertEqual(payload["policies"]["thresholds"], "Somente metas explicitamente configuradas; nenhum limite arbitrário.")
        self.assertEqual(payload["limitations"][0]["code"], "kpi_targets_not_configured")

    def test_meta_configurada_gera_excecao_com_valor_referencia_e_desvio(self):
        repository = _InsightsRepository(with_targets=True)
        payload = self._facade(repository).insights(self.filters)
        target = next(item for item in payload["exceptions"] if item["type"] == "configured_kpi_target")

        self.assertEqual(target["reference_value"], 80.0)
        self.assertLess(target["current_value"], target["reference_value"])
        self.assertAlmostEqual(target["deviation"], target["current_value"] - 80.0)
        self.assertEqual(target["evidence"][0]["source"], "metas_indicadores_teste")
        self.assertEqual(repository.calls["targets"], 1)

    def test_periodo_historico_nao_rotula_estado_aberto_como_parada_atual(self):
        historical = AnalyticsFilter(
            datetime(2026, 8, 24, 8, 0),
            datetime(2026, 8, 24, 11, 0),
            setor="Dobra",
            recurso="1303",
        )
        payload = self._facade(_NoTargetInsightsRepository()).insights(historical)
        types = [item["type"] for item in payload["exceptions"]]
        self.assertNotIn("current_unplanned_downtime", types)
        self.assertIn("physical_downtime_in_period", types)

    def test_filtros_sao_repassados_em_consultas_bulk_sem_consulta_por_recurso(self):
        repository = _InsightsRepository(with_targets=True)
        self._facade(repository).insights(self.filters)

        self.assertLessEqual(repository.calls["facts"], 2)
        self.assertLessEqual(repository.calls["states"], 2)
        self.assertLessEqual(repository.calls["quantities"], 2)
        self.assertLessEqual(repository.calls["rateios"], 2)
        for source, filters in repository.received_filters:
            if source == "targets":
                self.assertEqual(filters["setor"], "Dobra")
                self.assertEqual(filters["recurso"], "1303")
                continue
            self.assertEqual(filters.get("setor"), "Dobra")
            self.assertEqual(filters.get("recurso"), "1303")

    def test_endpoint_de_explicacao_rejeita_kpi_desconhecido_no_dominio(self):
        facade = self._facade(_NoTargetInsightsRepository())
        with self.assertRaisesRegex(ValueError, "não suportado"):
            facade.explain_kpi("inventado", self.filters)


if __name__ == "__main__":
    unittest.main()
