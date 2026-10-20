"""Explicação de valor ``kpi.*``: OEE e os percentuais de tempo da Visão Geral.

Contrato: ``docs/superpowers/specs/2026-10-19-explicacao-valor-contrato.md``.
A explicação só explica: o ``value`` é o número do cartão (``kpis`` ou
``kpis_estendidos`` do ``get_overview``) e a árvore fecha com ele.
"""

from __future__ import annotations

import copy
import unittest
from datetime import datetime

from fastapi.testclient import TestClient

from backend.api.database import get_database
from backend.api.dependencies.auth import get_current_user, require_csrf
from backend.api.main import create_app
from backend.api.routers.explanation import explain_for_user
from mes.ai.explanation_context import build_explanation_context
from mes.analytics.oee import PERFORMANCE_ABOVE_LIMIT_ALERT, RESULT_ORIGIN_NO_DEMAND
from mes.contracts import AnalyticsFilter
from mes.services.frontend_facade import FrontendBackendFacade
from mes.services.kpi_explanation import KpiExplanationService
from mes.services.metric_explanation import UnknownMetricError
from tests.test_standard_time import _settings
from tests.test_value_explanation import AGORA, URL, _ApiRepo, _BaseRepo, _user

INICIO = datetime(2026, 8, 18)
FIM = datetime(2026, 8, 21)
PERIOD = {"inicio": "2026-08-18T00:00:00", "fim": "2026-08-21T00:00:00"}

RATIOS = (
    ("kpi.disponibilidade", "kpis", "availability"),
    ("kpi.performance", "kpis", "performance"),
    ("kpi.ae", "kpis_estendidos", "ae"),
    ("kpi.produtividade", "kpis_estendidos", "productivity"),
    ("kpi.utilizacao", "kpis_estendidos", "utilization"),
)


def _filters(**extra):
    return AnalyticsFilter(INICIO, FIM, **extra)


def _facade(repo):
    return FrontendBackendFacade(repo, now_func=lambda: AGORA)


def _explain(repo, metric, filters=None):
    facade = _facade(repo)
    service = KpiExplanationService(facade.management, now_func=lambda: AGORA)
    return service.explain(metric, filters or _filters()).to_dict()


class _OverviewStub:
    """Entrega um overview real já adulterado, para bordas que o SQL não produz fácil."""

    def __init__(self, repo, mutate):
        self._management = _facade(repo).management
        self._mutate = mutate

    def get_overview(self, filters):
        overview = copy.deepcopy(self._management.get_overview(filters))
        self._mutate(overview)
        return overview

    def _now(self):
        return AGORA


def _stub_tree(repo, metric, mutate):
    service = KpiExplanationService(_OverviewStub(repo, mutate), now_func=lambda: AGORA)
    return service.explain(metric, _filters()).to_dict()


class KpiValueTests(unittest.TestCase):
    def test_valor_e_o_mesmo_do_cartao_da_visao_geral(self):
        repo = _ApiRepo()
        overview = _facade(repo).management.get_overview(_filters())
        self.assertEqual(_explain(repo, "kpi.oee")["value"], overview["kpis"]["oee"]["value"])
        for metric, section, key in RATIOS:
            with self.subTest(metric):
                tree = _explain(repo, metric)
                self.assertEqual(tree["kind"], "value")
                self.assertEqual(tree["unit"], "pct")
                self.assertEqual(tree["value"], overview[section][key]["value"])
                self.assertTrue(tree["rule"])
                self.assertTrue(tree["reason"])

    def test_percentuais_fecham_pela_soma_das_bases_dos_recursos(self):
        repo = _ApiRepo()
        for metric, _section, _key in RATIOS:
            with self.subTest(metric):
                tree = _explain(repo, metric)
                self.assertTrue(tree["reconciliation"]["ok"], tree["reconciliation"])
                self.assertEqual(tree["reconciliation"]["diff"], 0.0)
                self.assertEqual(tree["reconciliation"]["method"], "soma_das_bases_dos_recursos")

    def test_arvore_tem_numerador_denominador_e_depois_setor_recurso(self):
        tree = _explain(_ApiRepo(), "kpi.disponibilidade")
        labels = [node["label"] for node in tree["children"]]
        self.assertEqual(labels[:2], ["Numerador: Tempo trabalhado", "Denominador: Tempo disponível"])
        self.assertEqual([node["kind"] for node in tree["children"][:2]], ["input", "input"])
        sector = next(node for node in tree["children"] if node["kind"] == "sector")
        self.assertEqual(sector["label"], "Dobra")
        self.assertEqual(sector["children"][0]["kind"], "resource")
        self.assertEqual(sector["children"][0]["label"], "DOBRA1")

    def test_oee_fecha_pelo_produto_dos_componentes_e_aponta_para_eles(self):
        repo = _ApiRepo()
        tree = _explain(repo, "kpi.oee")
        self.assertEqual(tree["reconciliation"]["method"], "produto_dos_componentes")
        self.assertTrue(tree["reconciliation"]["ok"])
        inputs = {node["label"]: node for node in tree["children"] if node["kind"] == "input"}
        self.assertEqual(list(inputs), ["Disponibilidade", "Performance", "FTT"])
        self.assertEqual(inputs["Disponibilidade"]["value"], 100.0)
        self.assertEqual(inputs["Performance"]["value"], 25.0)
        self.assertEqual(inputs["FTT"]["value"], 90.0)
        self.assertEqual(tree["value"], 22.5)
        self.assertTrue(any("mesmo do cartão FTT" in note for note in tree["notes"]))

    def test_notas_de_utilizacao_e_de_indicador_so_no_total(self):
        repo = _ApiRepo()
        utilizacao = _explain(repo, "kpi.utilizacao")
        self.assertTrue(any("mesmas bases da Disponibilidade" in n for n in utilizacao["notes"]))
        for metric in ("kpi.ae", "kpi.produtividade", "kpi.utilizacao"):
            with self.subTest(metric):
                notes = _explain(repo, metric)["notes"]
                self.assertTrue(any("só no total" in note for note in notes))

    def test_filtro_de_setor_sem_dado_nao_quebra(self):
        tree = _explain(_ApiRepo(), "kpi.performance", _filters(setor="Solda"))
        self.assertEqual(tree["kind"], "value")
        self.assertTrue(tree["reconciliation"]["ok"], tree["reconciliation"])


class KpiEdgeTests(unittest.TestCase):
    def test_periodo_sem_dado_fica_indisponivel_e_explica(self):
        for metric in ("kpi.oee", "kpi.disponibilidade", "kpi.performance"):
            with self.subTest(metric):
                tree = _explain(_BaseRepo(), metric)
                self.assertEqual(tree["kind"], "value")
                self.assertTrue(tree["reason"])
                self.assertTrue(tree["reconciliation"]["ok"], tree["reconciliation"])

    def test_performance_acima_de_100_gera_alerta_sem_cortar_o_valor(self):
        def mutate(overview):
            overview["kpi_calculation"]["alerts"] = [PERFORMANCE_ABOVE_LIMIT_ALERT]
            for row in overview["resource_kpis"]:
                row.setdefault("kpi_calculation", {})["alerts"] = [PERFORMANCE_ABOVE_LIMIT_ALERT]

        for metric in ("kpi.oee", "kpi.performance", "kpi.ae"):
            with self.subTest(metric):
                notes = _stub_tree(_ApiRepo(), metric, mutate)["notes"]
                self.assertTrue(any(PERFORMANCE_ABOVE_LIMIT_ALERT in n and "sem corte" in n for n in notes))
                self.assertTrue(any("Recursos com Performance acima de 100%: DOBRA1" in n for n in notes))
        # Disponibilidade não usa a Performance: não herda o alerta.
        notes = _stub_tree(_ApiRepo(), "kpi.disponibilidade", mutate)["notes"]
        self.assertFalse(any(PERFORMANCE_ABOVE_LIMIT_ALERT in n for n in notes))

    def test_pecas_boas_sem_tempo_padrao_avisa_que_a_performance_fica_menor(self):
        def mutate(overview):
            overview["sector_kpis"][0]["pecas_boas_sem_tempo_padrao"] = 7

        notes = _stub_tree(_ApiRepo(), "kpi.performance", mutate)["notes"]
        self.assertTrue(any("7 peça(s) boa(s) sem tempo padrão" in note for note in notes))

    def test_periodo_todo_sem_demanda_cita_a_regra_e_nao_a_conta(self):
        def mutate(overview):
            overview["kpi_calculation"]["result_origin"] = RESULT_ORIGIN_NO_DEMAND

        notes = _stub_tree(_ApiRepo(), "kpi.disponibilidade", mutate)["notes"]
        self.assertTrue(any("regra, não da conta das horas" in n for n in notes), notes)

    def test_id_desconhecido_levanta_unknown_metric(self):
        facade = _facade(_ApiRepo())
        service = KpiExplanationService(facade.management)
        with self.assertRaises(UnknownMetricError):
            service.explain("kpi.inexistente", _filters())


class KpiEndpointTests(unittest.TestCase):
    def setUp(self):
        db = _ApiRepo()
        self.app = create_app(settings=_settings(), database_factory=lambda: db)
        self.app.dependency_overrides[get_database] = lambda: db
        self.app.dependency_overrides[require_csrf] = lambda: None
        self.app.dependency_overrides[get_current_user] = lambda: _user("gestor", management=True)
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)
        self.facade = _facade(db)

    def test_endpoint_devolve_o_mesmo_valor_do_overview(self):
        overview = self.client.get("/api/v1/management/overview", params=PERIOD).json()
        for metric, value in (
            ("kpi.oee", overview["kpis"]["oee"]["value"]),
            ("kpi.disponibilidade", overview["kpis"]["availability"]["value"]),
            ("kpi.ae", overview["kpis_estendidos"]["ae"]["value"]),
        ):
            with self.subTest(metric):
                response = self.client.get(URL, params={"metric": metric, **PERIOD})
                self.assertEqual(response.status_code, 200, response.text)
                body = response.json()
                self.assertEqual(body["kind"], "value")
                self.assertEqual(body["value"], value)
                self.assertTrue(body["reconciliation"]["ok"])

    def test_id_kpi_desconhecido_vira_422(self):
        response = self.client.get(URL, params={"metric": "kpi.inexistente", **PERIOD})
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["code"], "unknown_metric")

    def test_operador_sem_gestao_continua_barrado(self):
        self.app.dependency_overrides[get_current_user] = lambda: _user("operador", management=False)
        response = self.client.get(URL, params={"metric": "kpi.oee", **PERIOD})
        self.assertIn(response.status_code, (401, 403))


class KpiAiContextTests(unittest.TestCase):
    def test_contexto_da_ia_usa_a_mesma_arvore_e_cita_as_entradas(self):
        facade = _facade(_ApiRepo())
        explanation = explain_for_user(
            facade, "kpi.oee", _filters(), _user("gestor", management=True)
        )
        context = build_explanation_context(explanation, max_tokens=4000)
        self.assertIn("22,5", context.replace(".", ","))
        self.assertIn("Disponibilidade", context)
        self.assertIn("Performance", context)
        self.assertIn("FTT", context)


if __name__ == "__main__":
    unittest.main()
