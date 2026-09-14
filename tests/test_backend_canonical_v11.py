from datetime import datetime, time
import unittest

from mes.contracts import AnalyticsFilter
from mes.domain import DataAvailability
from mes.services.audit import AuditService
from mes.services.calendar import CalendarService
from mes.services.frontend_facade import FrontendBackendFacade
from mes.services.industrial_analytics import IndustrialAnalyticsService
from mes.services.management import ManagementService
from app.database.schema import SCHEMA_VERSION


class _CanonicalRepo:
    def listar_fatos_operacionais_periodo(self, *_args, **_kwargs):
        return [
            {
                "id": 1,
                "op": "OP1",
                "tipo_setor": "Dobra",
                "maquina": "DOBRA1",
                "status": "Finalizado",
                "data_inicio": datetime(2026, 8, 19, 8, 0),
                "data_fim": datetime(2026, 8, 19, 9, 0),
                "operador_inicio": "A",
                "quantidade": 10,
                "quantidade_boa": 5,
                "quantidade_refugo": 0,
                "quantidade_retrabalho": 0,
                "produto_codigo": "P1",
                "numero_operacao": "20",
                "tempo_medio_segundos": 100,
                "eventos": [
                    {"id": 1, "estado": "producao", "data_hora": datetime(2026, 8, 19, 8, 0)},
                    {"id": 2, "estado": "finalizado", "data_hora": datetime(2026, 8, 19, 9, 0)},
                ],
            },
            {
                "id": 2,
                "op": "OP2",
                "tipo_setor": "Dobra",
                "maquina": "DOBRA1",
                "status": "Finalizado",
                "data_inicio": datetime(2026, 8, 19, 8, 0),
                "data_fim": datetime(2026, 8, 19, 9, 0),
                "operador_inicio": "B",
                "quantidade": 10,
                "quantidade_boa": 4,
                "quantidade_refugo": 0,
                "quantidade_retrabalho": 0,
                "produto_codigo": "P2",
                "numero_operacao": "20",
                "tempo_medio_segundos": 100,
                "eventos": [
                    {"id": 3, "estado": "producao", "data_hora": datetime(2026, 8, 19, 8, 0)},
                    {"id": 4, "estado": "finalizado", "data_hora": datetime(2026, 8, 19, 9, 0)},
                ],
            },
        ]

    def listar_estados_recurso_periodo(self, *_args, categoria=None, **_kwargs):
        rows = [
            {
                "id": 10,
                "recurso": "DOBRA1",
                "tipo_setor": "Dobra",
                "categoria": "producao",
                "data_inicio": datetime(2026, 8, 19, 8, 0),
                "data_fim": datetime(2026, 8, 19, 9, 0),
                "inicio_periodo": datetime(2026, 8, 19, 8, 0),
                "fim_periodo": datetime(2026, 8, 19, 9, 0),
                "segundos_periodo": 3600.0,
                "origem": "apontamento_operador",
            }
        ]
        if categoria:
            rows = [row for row in rows if row["categoria"] == categoria]
        return rows

    def listar_estados_recurso_atuais(self, **_kwargs):
        return []

    def listar_eventos_quantidade_periodo(self, *_args, **_kwargs):
        return [
            {"tipo": "boa", "quantidade": 5, "tipo_setor": "Dobra", "produto_codigo": "P1"},
            {"tipo": "boa", "quantidade": 4, "tipo_setor": "Dobra", "produto_codigo": "P2"},
        ]

    def listar_tempos_nesting_corte(self, **_kwargs):
        return []

    def possui_calendario_produtivo(self, *_args):
        return False

    def listar_rateios_tempo_periodo(self, *_args, **_kwargs):
        return []

    def listar_inconsistencias_dados(self, **_kwargs):
        return []

    def listar_configuracao_capacidade_recursos(self, **_kwargs):
        return []

    def listar_nestings_corte_por_op(self, _op):
        return []

    def get_op_timeline(self, _op):
        return []


class CanonicalPhysicalSourceTests(unittest.TestCase):
    def setUp(self):
        self.repo = _CanonicalRepo()
        self.filters = AnalyticsFilter(
            datetime(2026, 8, 19, 0, 0),
            datetime(2026, 8, 19, 23, 59),
        )

    def test_management_prefere_estado_fisico_canonico(self):
        result = ManagementService(self.repo).get_overview(self.filters)
        self.assertEqual(result["hours"]["physical_measured_seconds"], 3600)
        self.assertEqual(
            result["data_quality"]["physical_state_source"],
            "eventos_estado_recurso",
        )
        self.assertEqual(result["production"]["good"], 9)

    def test_analytics_prefere_estado_fisico_canonico(self):
        result = IndustrialAnalyticsService(self.repo).time_breakdown(self.filters)
        self.assertEqual(result["physical_seconds"], 3600)
        self.assertEqual(result["totals"]["producao"], 3600)
        self.assertEqual(result["physical_state_source"], "eventos_estado_recurso")

    def test_estado_fisico_canonico_sem_parada_nao_cai_para_timeline_da_op(self):
        result = IndustrialAnalyticsService(self.repo).downtimes(self.filters)
        self.assertEqual(result["items"], [])
        self.assertEqual(result["total_seconds"], 0)

    def test_regra_canonica_calcula_kpis_sem_fazer_setup_penalizar_performance(self):
        class SimulationRepo(_CanonicalRepo):
            def listar_estados_recurso_periodo(self, *_args, categoria=None, **_kwargs):
                rows = [
                    {"id": 10, "recurso": "DOBRA1", "tipo_setor": "Dobra", "categoria": "producao", "data_inicio": datetime(2026, 8, 19, 8, 0), "data_fim": datetime(2026, 8, 19, 9, 0)},
                    {"id": 11, "recurso": "DOBRA1", "tipo_setor": "Dobra", "categoria": "setup", "data_inicio": datetime(2026, 8, 19, 9, 0), "data_fim": datetime(2026, 8, 19, 9, 10)},
                    {"id": 12, "recurso": "DOBRA1", "tipo_setor": "Dobra", "categoria": "parada", "data_inicio": datetime(2026, 8, 19, 9, 10), "data_fim": datetime(2026, 8, 19, 9, 20)},
                    {"id": 13, "recurso": "DOBRA1", "tipo_setor": "Dobra", "categoria": "fila", "data_inicio": datetime(2026, 8, 19, 9, 20), "data_fim": datetime(2026, 8, 19, 9, 30)},
                ]
                if categoria:
                    rows = [row for row in rows if row["categoria"] == categoria]
                return rows

        result = ManagementService(SimulationRepo()).get_overview(self.filters)
        simulated = ManagementService(SimulationRepo(), simulation_mode=True).get_overview(self.filters)
        self.assertEqual(result["kpis"], simulated["kpis"])
        simulation = simulated["simulation"]
        self.assertAlmostEqual(simulation["time_bases"]["available_seconds"], 5400)
        self.assertAlmostEqual(simulation["time_bases"]["worked_seconds"], 4200)
        self.assertAlmostEqual(simulation["time_bases"]["standard_run_seconds"], 900)
        self.assertAlmostEqual(simulation["time_bases"]["supporting_productive_seconds"], 600)
        self.assertAlmostEqual(result["kpis"]["availability"]["value"], 4200 / 5400 * 100)
        self.assertAlmostEqual(result["kpis"]["performance"]["value"], 1500 / 4200 * 100)
        self.assertEqual(result["kpis"]["ftt"]["value"], 100)
        self.assertEqual(simulation["policy"], "canonical_oee")

    def test_ftt_usa_a_mesma_regra_em_modo_normal_e_simulacao(self):
        normal = IndustrialAnalyticsService(self.repo).quality(self.filters)
        simulated = IndustrialAnalyticsService(self.repo, simulation_mode=True).quality(self.filters)
        self.assertEqual(normal["ftt"], simulated["ftt"])
        self.assertEqual(normal["ftt"]["value"], 100)
        self.assertEqual(normal["ftt"]["availability"], DataAvailability.AVAILABLE.value)
        self.assertEqual(simulated["ftt"]["value"], 100)
        self.assertEqual(simulated["ftt"]["availability"], DataAvailability.AVAILABLE.value)


class _CalendarAggregateRepo:
    def listar_turnos_recurso(self, _resource):
        return [{
            "id": 1,
            "calendario_codigo": "PADRAO",
            "calendario_nome": "Padrão",
            "timezone": "America/Sao_Paulo",
            "nome": "Dia",
            "dia_semana": 2,  # quarta-feira, 19/08/2026
            "hora_inicio": time(8, 0),
            "hora_fim": time(16, 0),
            "cruza_meia_noite": False,
            "minutos_intervalo": 60,
        }]

    def listar_intervalos_turno(self, _turno_id):
        return []

    def listar_excecoes_calendario_periodo(self, *_args):
        return []


class _CalendarExactRepo(_CalendarAggregateRepo):
    def listar_intervalos_turno(self, _turno_id):
        return [{
            "hora_inicio": time(12, 0),
            "hora_fim": time(13, 0),
            "desconta_tempo": True,
        }]


class CalendarV11Tests(unittest.TestCase):
    def test_recorte_parcial_nao_inventa_posicao_do_intervalo(self):
        result = CalendarService(_CalendarAggregateRepo()).period_summary(
            "R1",
            datetime(2026, 8, 19, 11, 30),
            datetime(2026, 8, 19, 12, 30),
        )
        self.assertEqual(result["availability"], DataAvailability.PARTIAL.value)
        self.assertIsNone(result["tempo_disponivel_segundos"])

    def test_turno_completo_com_intervalo_agregado_conhece_total_mas_nao_inventa_timeline(self):
        result = CalendarService(_CalendarAggregateRepo()).period_summary(
            "R1",
            datetime(2026, 8, 19, 8, 0),
            datetime(2026, 8, 19, 16, 0),
        )
        self.assertEqual(result["availability"], DataAvailability.PARTIAL.value)
        self.assertEqual(result["tempo_disponivel_segundos"], 7 * 3600)
        self.assertEqual(result["segmentos_disponiveis"], [])

    def test_intervalo_exato_e_descontado_no_recorte(self):
        result = CalendarService(_CalendarExactRepo()).period_summary(
            "R1",
            datetime(2026, 8, 19, 11, 30),
            datetime(2026, 8, 19, 12, 30),
        )
        self.assertEqual(result["availability"], DataAvailability.AVAILABLE.value)
        self.assertEqual(result["tempo_disponivel_segundos"], 1800)

    def test_consulta_repetida_reutiliza_catalogo_durante_o_caso_de_uso(self):
        class CountingRepo(_CalendarExactRepo):
            def __init__(self):
                self.turn_calls = 0
                self.interval_calls = 0
                self.exception_calls = 0

            def listar_turnos_recurso(self, resource):
                self.turn_calls += 1
                return super().listar_turnos_recurso(resource)

            def listar_intervalos_turno(self, shift_id):
                self.interval_calls += 1
                return super().listar_intervalos_turno(shift_id)

            def listar_excecoes_calendario_periodo(self, *args):
                self.exception_calls += 1
                return super().listar_excecoes_calendario_periodo(*args)

        repo = CountingRepo()
        service = CalendarService(repo)
        start = datetime(2026, 8, 19, 8, 0)
        end = datetime(2026, 8, 19, 16, 0)
        service.period_summary("R1", start, end)
        service.period_summary("R1", start, end)

        self.assertEqual(repo.turn_calls, 1)
        self.assertEqual(repo.interval_calls, 1)
        self.assertEqual(repo.exception_calls, 1)


class AuditV11Tests(unittest.TestCase):
    def test_estado_desconhecido_e_producao_sem_op_sao_explicitados(self):
        service = AuditService(now_func=lambda: datetime(2026, 8, 19, 10, 0))
        states = [
            {
                "id": 1, "recurso": "R1", "tipo_setor": "Dobra",
                "categoria": "desconhecido",
                "data_inicio": datetime(2026, 8, 19, 8, 0),
                "data_fim": datetime(2026, 8, 19, 8, 30),
            },
            {
                "id": 2, "recurso": "R2", "tipo_setor": "Dobra",
                "categoria": "producao",
                "data_inicio": datetime(2026, 8, 19, 8, 0),
                "data_fim": datetime(2026, 8, 19, 9, 0),
            },
        ]
        types = {issue["type"] for issue in service.inspect_resource_states(states, facts=[])}
        self.assertIn("estado_fisico_desconhecido", types)
        self.assertIn("recurso_produzindo_sem_op", types)

    def test_rateio_precisa_conservar_tempo_fisico(self):
        issues = AuditService().inspect_rateio([{
            "recurso": "R1",
            "segundos_fisicos_periodo": 3600,
            "rateios": [{"segundos_atribuidos_periodo": 1700}, {"segundos_atribuidos_periodo": 1700}],
        }])
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]["type"], "rateio_nao_conserva_tempo_fisico")

    def test_fim_turno_sem_evento_e_inconsistencia(self):
        rows = [{
            "id": 1,
            "op": "OP1",
            "maquina": "R1",
            "tipo_setor": "Dobra",
            "numero_operacao": "20",
            "data_inicio": datetime(2026, 8, 19, 17, 0),
            "data_fim": datetime(2026, 8, 19, 18, 0),
            "eventos": [],
        }]
        issues = AuditService().inspect_shift_boundaries(
            rows,
            inicio=datetime(2026, 8, 19, 0, 0),
            fim=datetime(2026, 8, 19, 23, 59),
        )
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]["start"], datetime(2026, 8, 19, 17, 30))


class FrontendFacadeTests(unittest.TestCase):
    def test_capabilities_centraliza_regras_que_o_frontend_nao_pode_reinventar(self):
        facade = FrontendBackendFacade(_CanonicalRepo())
        capabilities = facade.capabilities()
        self.assertEqual(capabilities["schema_version"], SCHEMA_VERSION)
        self.assertEqual(capabilities["calculation_policy"], "backend_only")
        self.assertEqual(capabilities["manufacturing_rules"]["produced_quantity"], "good_only")
        self.assertEqual(capabilities["manufacturing_rules"]["shift_end_boundaries"], ["17:30", "21:30"])
        self.assertFalse(capabilities["ui_policy"]["management_correction_or_edit_tab"])
        self.assertFalse(capabilities["pending_official_definition"]["oee_ftt_with_scrap_rework"])

    def test_facade_entrega_secoes_sem_calculo_no_frontend(self):
        facade = FrontendBackendFacade(
            _CanonicalRepo(),
            now_func=lambda: datetime(2026, 8, 19, 10, 0),
        )
        filters = AnalyticsFilter(
            datetime(2026, 8, 19, 0, 0),
            datetime(2026, 8, 19, 23, 59),
        )
        analytics = facade.analises(filters)
        self.assertIn("tempos", analytics)
        self.assertIn("paradas", analytics)
        self.assertIn("qualidade", analytics)
        self.assertEqual(analytics["oee"]["availability"], DataAvailability.AVAILABLE.value)
        self.assertAlmostEqual(analytics["oee"]["value"], 25.0)
        self.assertEqual(analytics["oee"]["evolution"]["availability"], "dados_insuficientes")

    def test_destaques_de_setor_selecionam_extremos_das_metricas_canonicas(self):
        sectors = [
            {"setor": "Dobra", "producao_boa": 120, "refugo": 2, "ops": 3, "tempo_producao_segundos": 7200, "tempo_parada_segundos": 300},
            {"setor": "Usinagem", "producao_boa": 90, "refugo": 8, "ops": 2, "tempo_producao_segundos": 3600, "tempo_parada_segundos": 900},
            {"setor": "Serra", "producao_boa": 40, "refugo": 1, "ops": 1, "tempo_producao_segundos": 1800, "tempo_parada_segundos": 120},
            {"setor": "Sem dados", "producao_boa": 0, "refugo": 0, "ops": 0, "tempo_producao_segundos": 0, "tempo_parada_segundos": 0},
        ]

        result = FrontendBackendFacade._sector_highlights(sectors)

        self.assertEqual(
            [(item["key"], item["sector"], item["value"]) for item in result],
            [
                ("maior_producao_boa", "Dobra", 120.0),
                ("maior_refugo", "Usinagem", 8.0),
                ("menor_tempo_producao", "Serra", 1800.0),
                ("maior_tempo_parada", "Usinagem", 900.0),
            ],
        )

    def test_destaques_de_setor_vazios_nao_inventam_valores(self):
        self.assertEqual(FrontendBackendFacade._sector_highlights([]), [])


class _AndonRepo(_CanonicalRepo):
    def __init__(self):
        self.catalog_calls = 0
        self.current_state_calls = 0
        self.fact_calls = 0

    @staticmethod
    def _states():
        start = datetime(2026, 8, 19, 9, 0)
        return [
            {"id": 1, "recurso": "R-PROD", "tipo_setor": "Dobra", "categoria": "producao", "op": "OP-ANDON", "numero_operacao": "20", "produto_codigo": "P-ANDON", "data_inicio": start},
            {"id": 2, "recurso": "R-STOP", "tipo_setor": "Dobra", "categoria": "parada", "motivo": "Falta de material", "data_inicio": start},
            {"id": 3, "recurso": "R-SETUP", "tipo_setor": "Usinagem", "categoria": "setup", "data_inicio": start},
            {"id": 4, "recurso": "R-REWORK", "tipo_setor": "Usinagem", "categoria": "retrabalho", "data_inicio": start},
            {"id": 5, "recurso": "R-QUEUE", "tipo_setor": "Serra", "categoria": "fila", "data_inicio": start},
            {"id": 6, "recurso": "R-NOOP", "tipo_setor": "Solda Aço", "categoria": "atividade_sem_op", "data_inicio": start},
            {"id": 7, "recurso": "R-OFF", "tipo_setor": "Pintura", "categoria": "fora_turno", "data_inicio": start},
            {"id": 8, "recurso": "R-UNKNOWN", "tipo_setor": "Corte", "categoria": "desconhecido", "data_inicio": start},
        ]

    def listar_recursos_pcfactory(self, *_args, **_kwargs):
        self.catalog_calls += 1
        sectors = {
            "R-PROD": "Dobra", "R-STOP": "Dobra", "R-SETUP": "Usinagem",
            "R-REWORK": "Usinagem", "R-QUEUE": "Serra", "R-NOOP": "Solda Aço",
            "R-OFF": "Pintura", "R-UNKNOWN": "Corte", "R-NOSTATE": "Corte",
        }
        return [
            {"codigo": code, "nome": f"Máquina {code}", "tipo_setor": sector, "habilitado": True}
            for code, sector in sectors.items()
        ]

    def listar_estados_recurso_atuais(self, **_kwargs):
        self.current_state_calls += 1
        return self._states()

    def listar_estados_recurso_periodo(self, *_args, categoria=None, **_kwargs):
        rows = [dict(row, data_fim=datetime(2026, 8, 19, 10, 0)) for row in self._states()]
        return [row for row in rows if not categoria or row["categoria"] == categoria]

    def listar_fatos_operacionais_periodo(self, *_args, **_kwargs):
        self.fact_calls += 1
        return [{
            "id": 91,
            "op": "OP-ANDON",
            "tipo_setor": "Dobra",
            "maquina": "R-PROD",
            "status": "Em processo",
            "data_inicio": datetime(2026, 8, 19, 9, 0),
            "data_fim": None,
            "operador_inicio": "Operador A",
            "quantidade": 20,
            "quantidade_planejada_pcp": 20,
            "quantidade_boa": 8,
            "quantidade_refugo": 1,
            "quantidade_retrabalho": 2,
            "produto_codigo": "P-ANDON",
            "produto_descricao": "Produto do Andon",
            "numero_operacao": "20",
            "descricao_operacao": "DOBRA",
            "tempo_medio_segundos": 100,
            "eventos": [],
        }]

    def listar_eventos_quantidade_periodo(self, *_args, **_kwargs):
        return [{"tipo": "boa", "quantidade": 8, "tipo_setor": "Dobra", "recurso": "R-PROD"}]


class AndonProjectionTests(unittest.TestCase):
    def setUp(self):
        self.repo = _AndonRepo()
        self.filters = AnalyticsFilter(
            datetime(2026, 8, 19, 0, 0),
            datetime(2026, 8, 19, 23, 59),
        )
        self.result = FrontendBackendFacade(
            self.repo,
            now_func=lambda: datetime(2026, 8, 19, 10, 0),
        ).andon(self.filters)

    def test_snapshot_expoe_somente_recursos_com_apontamento_ativo(self):
        self.assertEqual(self.result["resource_count"], 5)
        self.assertEqual(
            [sector["name"] for sector in self.result["sectors"]],
            ["Corte", "Caldeiraria", "Solda", "Pintura"],
        )
        resources = {
            item["code"]: item
            for sector in self.result["sectors"]
            for item in sector["resources"]
        }
        self.assertEqual(
            {item["state"]["category"] for item in resources.values()},
            {"producao", "parada", "setup", "retrabalho", "atividade_sem_op"},
        )
        self.assertEqual(resources["R-STOP"]["state"]["reason"], "Falta de material")
        self.assertEqual(resources["R-STOP"]["state"]["display_label"], "Falta de material")
        self.assertIsNone(resources["R-NOOP"]["operation"])
        self.assertNotIn("R-NOSTATE", resources)
        self.assertNotIn("R-QUEUE", resources)
        self.assertNotIn("R-OFF", resources)
        self.assertNotIn("R-UNKNOWN", resources)
        self.assertEqual(resources["R-PROD"]["panel"], "Caldeiraria")
        self.assertEqual(resources["R-PROD"]["group"], "Dobra")

    def test_snapshot_expoe_op_quantidade_e_indicadores_canonicos_por_recurso(self):
        resources = {
            item["code"]: item
            for sector in self.result["sectors"]
            for item in sector["resources"]
        }
        production = resources["R-PROD"]
        self.assertEqual(production["operation"]["op"], "OP-ANDON")
        self.assertEqual(production["operation"]["operation"], "20")
        self.assertEqual(production["operation"]["product_description"], "Produto do Andon")
        self.assertEqual(production["operation"]["good_quantity"], 8)
        self.assertEqual(production["operation"]["planned_quantity"], 20)
        self.assertAlmostEqual(production["metrics"]["oee"]["value"], 800 / 3600 * 100)
        self.assertAlmostEqual(production["metrics"]["availability"]["value"], 100.0)
        self.assertAlmostEqual(production["metrics"]["performance"]["value"], 800 / 3600 * 100)
        self.assertAlmostEqual(production["metrics"]["ftt"]["value"], 100.0)
        self.assertEqual(production["metrics"]["oee"]["availability"], "disponivel")
        self.assertEqual(
            resources["R-STOP"]["metrics"]["availability"]["value"],
            0.0,
        )
        self.assertIsNone(resources["R-STOP"]["metrics"]["oee"]["value"])
        self.assertIsNotNone(self.result["summary"]["oee"]["value"])
        self.assertEqual(self.result["summary"]["oee"]["availability"], "disponivel")
        self.assertEqual(self.result["summary"]["ftt"]["value"], 100.0)

    def test_snapshot_nao_faz_consulta_por_maquina(self):
        self.assertEqual(self.repo.catalog_calls, 1)
        self.assertEqual(self.repo.current_state_calls, 1)
        self.assertEqual(self.repo.fact_calls, 2)

    def test_simulacao_usa_o_mesmo_oee_canonico_por_recurso_sem_inventar_valores(self):
        simulated = FrontendBackendFacade(
            _AndonRepo(),
            now_func=lambda: datetime(2026, 8, 19, 10, 0),
            simulation_mode=True,
        ).andon(self.filters)
        resources = [
            resource
            for sector in simulated["sectors"]
            for resource in sector["resources"]
        ]
        self.assertTrue(simulated["simulation_only"])
        self.assertEqual(simulated["summary"]["oee"], self.result["summary"]["oee"])
        normal_resources = {
            resource["code"]: resource
            for sector in self.result["sectors"]
            for resource in sector["resources"]
        }
        self.assertEqual(
            {resource["code"]: resource["metrics"] for resource in resources},
            {code: resource["metrics"] for code, resource in normal_resources.items()},
        )
        self.assertIsNotNone(normal_resources["R-PROD"]["metrics"]["oee"]["value"])
        self.assertNotIn("R-NOSTATE", normal_resources)
        self.assertFalse(self.result["simulation_only"])
        self.assertIsNotNone(self.result["summary"]["oee"]["value"])

    def test_snapshot_preserva_codigos_que_diferem_apenas_por_capitalizacao(self):
        class CaseSensitiveCatalogRepo(_AndonRepo):
            def listar_recursos_pcfactory(self, *_args, **_kwargs):
                return [
                    {"codigo": "SCCGMM", "nome": "Solda A", "tipo_setor": "Solda Aço", "habilitado": True},
                    {"codigo": "SCCGmm", "nome": "Solda B", "tipo_setor": "Solda Aço", "habilitado": True},
                ]

            def listar_estados_recurso_atuais(self, **_kwargs):
                start = datetime(2026, 8, 19, 9, 0)
                return [
                    {"recurso": "SCCGMM", "tipo_setor": "Solda Aço", "categoria": "producao", "data_inicio": start},
                    {"recurso": "SCCGmm", "tipo_setor": "Solda Aço", "categoria": "setup", "data_inicio": start},
                ]

            def listar_fatos_operacionais_periodo(self, *_args, **_kwargs):
                return []

            def listar_eventos_quantidade_periodo(self, *_args, **_kwargs):
                return []

        result = FrontendBackendFacade(
            CaseSensitiveCatalogRepo(), now_func=lambda: datetime(2026, 8, 19, 10, 0)
        ).andon(self.filters)
        codes = [
            resource["code"]
            for sector in result["sectors"]
            for resource in sector["resources"]
        ]
        self.assertEqual(result["resource_count"], 2)
        self.assertCountEqual(codes, ["SCCGMM", "SCCGmm"])

    def test_snapshot_vazio_permanece_sem_registros(self):
        class EmptyRepo(_AndonRepo):
            def listar_recursos_pcfactory(self, *_args, **_kwargs):
                return []

            def listar_estados_recurso_atuais(self, **_kwargs):
                return []

            def listar_estados_recurso_periodo(self, *_args, **_kwargs):
                return []

            def listar_fatos_operacionais_periodo(self, *_args, **_kwargs):
                return []

            def listar_eventos_quantidade_periodo(self, *_args, **_kwargs):
                return []

        result = FrontendBackendFacade(
            EmptyRepo(), now_func=lambda: datetime(2026, 8, 19, 10, 0)
        ).andon(self.filters)
        self.assertEqual(result["availability"], "sem_registros")
        self.assertEqual(
            [sector["name"] for sector in result["sectors"]],
            ["Corte", "Caldeiraria", "Solda", "Pintura"],
        )
        self.assertTrue(all(not sector["resources"] for sector in result["sectors"]))


if __name__ == "__main__":
    unittest.main()
