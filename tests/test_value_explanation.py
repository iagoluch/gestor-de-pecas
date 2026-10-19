"""Explicação de valor (peças boas, refugo, retrabalho, taxas): ``qtd.*``.

Contrato: ``docs/superpowers/specs/2026-10-19-explicacao-valor-contrato.md``.
A explicação só explica: o ``value`` tem que ser o mesmo número do
``get_overview`` (Visão Geral) e a árvore tem que fechar com ele.
"""

from __future__ import annotations

import unittest
from datetime import datetime

from fastapi.testclient import TestClient

from backend.api.database import get_database
from backend.api.dependencies.auth import get_current_user, require_csrf
from backend.api.main import create_app
from backend.api.routers.explanation import explain_for_user
from backend.api.schemas.auth import SessionUser
from mes.ai.explanation_context import build_explanation_context
from mes.contracts import AnalyticsFilter
from mes.services.frontend_facade import FrontendBackendFacade
from mes.services.management import ManagementService
from mes.services.metric_explanation import UnknownMetricError
from mes.services.value_explanation import MAX_LEAVES_PER_RESOURCE, ValueExplanationService
from tests.test_oee_consistency import _ThreeDayOeeRepo
from tests.test_standard_time import _settings

DIA = datetime(2026, 8, 19)
AGORA = datetime(2026, 8, 21, 12, 0)
URL = "/api/v1/management/explicacao"
OVERVIEW = "/api/v1/management/overview"
PERIOD = {"inicio": "2026-08-18T00:00:00", "fim": "2026-08-21T00:00:00"}


def _filters():
    return AnalyticsFilter(DIA, DIA.replace(hour=23, minute=59))


def _event(id_, tipo, qtd, setor, recurso, hora=10, **extra):
    return {
        "id": id_,
        "tipo": tipo,
        "quantidade": qtd,
        "op": extra.pop("op", "OP-1"),
        "tipo_setor": setor,
        "recurso": recurso,
        "operador": extra.pop("operador", "Maria"),
        "motivo": extra.pop("motivo", None),
        "origem": "gestor_pecas",
        "data_hora": datetime(2026, 8, 19, hora, 0),
        **extra,
    }


class _BaseRepo:
    """Repositório mínimo, sem fonte de eventos de quantidade (cai no fallback)."""

    def __init__(self, facts=None, cutting=None):
        self._facts = facts or []
        self._cutting = cutting or []

    def listar_fatos_operacionais_periodo(self, *_a, **_k):
        return [dict(row) for row in self._facts]

    def listar_estados_recurso_periodo(self, *_a, **_k):
        return []

    def listar_tempos_nesting_corte(self, **_k):
        return []

    def listar_producao_corte_periodo(self, *_a, **_k):
        return [dict(row) for row in self._cutting]

    def possui_calendario_produtivo(self, *_a):
        return False

    def listar_turnos_recurso(self, *_a):
        return []

    def listar_rateios_tempo_periodo(self, *_a, **_k):
        return []

    def listar_inconsistencias_dados(self, **_k):
        return []


class _EventRepo(_BaseRepo):
    def __init__(self, events, **kwargs):
        super().__init__(**kwargs)
        self._events = events

    def listar_eventos_quantidade_periodo(self, *_a, **_k):
        return [dict(row) for row in self._events]


def _cutting_row(op="OP-9", qtd=10, maquina="LASER1"):
    return {
        "codigo_tarefa": "T-1",
        "concluido_em": datetime(2026, 8, 19, 11, 0),
        "maquina": maquina,
        "codigo_op": op,
        "quantidade": qtd,
    }


def _events():
    return [
        _event(1, "boa", 9, "Dobra", "DOBRA1", op="OP-1"),
        _event(2, "boa", 5, "Dobra", "DOBRA1", hora=11, op="OP-2"),
        _event(3, "boa", 4, "Solda", "SOLDA1", op="OP-3"),
        _event(4, "refugo", 2, "Dobra", "DOBRA1", motivo="Trinca", op="OP-1"),
        _event(5, "retrabalho", 3, "Solda", "SOLDA1", motivo="Rebarba", op="OP-3"),
    ]


def _service(repo):
    management = ManagementService(repo, now_func=lambda: AGORA)
    return ValueExplanationService(management, repo), management


def _tree(repo, metric):
    service, management = _service(repo)
    return service.explain(metric, _filters()).to_dict(), management.get_overview(_filters())


def _leaves(nodes):
    for node in nodes:
        if not node["children"]:
            yield node
        else:
            yield from _leaves(node["children"])


class ValueEqualsOverviewTests(unittest.TestCase):
    def test_pecas_boas_fecha_com_a_visao_geral_incluindo_o_corte(self):
        repo = _EventRepo(_events(), cutting=[_cutting_row()])
        tree, overview = _tree(repo, "qtd.boa")

        self.assertEqual(tree["kind"], "value")
        self.assertEqual(tree["unit"], "pcs")
        self.assertEqual(tree["value"], overview["production"]["good"])
        self.assertEqual(tree["value"], 9 + 5 + 4 + 10)
        self.assertEqual(tree["reconciliation"]["sum"], tree["value"])
        self.assertTrue(tree["reconciliation"]["ok"])
        self.assertEqual(tree["reconciliation"]["diff"], 0.0)
        sectors = {node["label"]: node["value"] for node in tree["children"]}
        self.assertEqual(sectors, {"Dobra": 14.0, "Corte": 10.0, "Solda": 4.0})
        self.assertTrue(any("Corte" in note for note in tree["notes"]))

    def test_refugo_e_retrabalho_fecham_com_a_visao_geral(self):
        repo = _EventRepo(_events())
        for metric, key, expected in (
            ("qtd.refugo", "scrap", 2),
            ("qtd.retrabalho", "rework", 3),
        ):
            with self.subTest(metric):
                tree, overview = _tree(repo, metric)
                self.assertEqual(tree["value"], overview["production"][key])
                self.assertEqual(tree["value"], expected)
                self.assertTrue(tree["reconciliation"]["ok"])
                self.assertEqual(
                    sum(node["value"] for node in tree["children"]), tree["value"]
                )

    def test_arvore_setor_recurso_evento_com_detalhe_so_do_que_existe(self):
        tree, _ = _tree(_EventRepo(_events()), "qtd.refugo")

        sector = tree["children"][0]
        resource = sector["children"][0]
        leaf = resource["children"][0]
        self.assertEqual([sector["kind"], resource["kind"], leaf["kind"]], ["sector", "resource", "event"])
        self.assertEqual((sector["label"], resource["label"]), ("Dobra", "DOBRA1"))
        self.assertEqual(leaf["value"], 2.0)
        self.assertEqual(
            leaf["detail"],
            {
                "id": 4,
                "op": "OP-1",
                "operador": "Maria",
                "data_hora": "2026-08-19T10:00:00",
                "motivo": "Trinca",
                "origem": "gestor_pecas",
            },
        )
        # Registro sem motivo/operador não ganha chave inventada.
        sem_motivo = _event(7, "refugo", 1, "Dobra", "DOBRA1", operador="", motivo="")
        tree2, _ = _tree(_EventRepo([sem_motivo]), "qtd.refugo")
        detail = tree2["children"][0]["children"][0]["children"][0]["detail"]
        self.assertNotIn("motivo", detail)
        self.assertNotIn("operador", detail)

    def test_excluidos_mostram_os_outros_tipos_e_tipo_desconhecido(self):
        eventos = _events() + [_event(8, "sucata", 7, "Dobra", "DOBRA1")]
        tree, _ = _tree(_EventRepo(eventos), "qtd.boa")
        excluded = {item["label"]: item["value"] for item in tree["excluded"]}
        self.assertEqual(excluded["Refugo"], 2.0)
        self.assertEqual(excluded["Retrabalho"], 3.0)
        self.assertEqual(excluded["Lançamentos de tipo desconhecido"], 7.0)
        # O desconhecido não entra em nenhuma árvore nem no overview.
        self.assertEqual(tree["value"], 18.0)
        self.assertTrue(tree["reconciliation"]["ok"])

    def test_sem_registros_value_zero_com_motivo_do_overview(self):
        tree, overview = _tree(_EventRepo([]), "qtd.boa")
        self.assertEqual(tree["value"], 0.0)
        self.assertEqual(tree["children"], [])
        self.assertEqual(tree["reason"], overview["production"]["reason"])
        self.assertTrue(tree["reconciliation"]["ok"])


class RateExplanationTests(unittest.TestCase):
    def test_taxa_de_refugo_ignora_retrabalho_e_tem_entradas(self):
        repo = _EventRepo(_events(), cutting=[_cutting_row()])
        tree, overview = _tree(repo, "qtd.taxa_refugo")
        good = overview["production"]["good"]
        scrap = overview["production"]["scrap"]

        self.assertEqual(tree["unit"], "pct")
        self.assertAlmostEqual(tree["value"], scrap / (good + scrap) * 100)
        self.assertEqual([c["kind"] for c in tree["children"]], ["input", "input"])
        self.assertEqual(
            {c["label"]: c["value"] for c in tree["children"]},
            {"Peças boas": float(good), "Refugo": float(scrap)},
        )
        self.assertTrue(tree["reconciliation"]["ok"])
        self.assertAlmostEqual(tree["reconciliation"]["sum"], tree["value"])
        self.assertTrue(any("ignora o retrabalho" in note for note in tree["notes"]))
        self.assertEqual([x["label"] for x in tree["excluded"]], ["Retrabalho"])

    def test_ftt_igual_ao_da_visao_geral_e_inclui_retrabalho(self):
        repo = _EventRepo(_events(), cutting=[_cutting_row()])
        tree, overview = _tree(repo, "qtd.ftt")
        production = overview["production"]

        self.assertEqual(tree["value"], overview["kpis"]["ftt"]["value"])
        self.assertAlmostEqual(
            tree["value"],
            production["good"] / (production["good"] + production["scrap"] + production["rework"]) * 100,
        )
        self.assertEqual(
            [c["label"] for c in tree["children"]], ["Peças boas", "Refugo", "Retrabalho"]
        )
        self.assertTrue(tree["reconciliation"]["ok"])
        self.assertTrue(any("Por isso os dois percentuais" in note for note in tree["notes"]))
        self.assertTrue(any("tabelas Produção > OPs" in note for note in tree["notes"]))

    def test_taxas_sem_pecas_ficam_indisponiveis(self):
        for metric in ("qtd.taxa_refugo", "qtd.ftt"):
            with self.subTest(metric):
                tree, _ = _tree(_EventRepo([]), metric)
                self.assertIsNone(tree["value"])
                self.assertTrue(tree["reason"])
                self.assertTrue(tree["reconciliation"]["ok"])


class TruncationAndFallbackTests(unittest.TestCase):
    def test_corte_por_tamanho_mantem_total_e_fecha(self):
        total = MAX_LEAVES_PER_RESOURCE + 50
        eventos = [
            _event(i, "boa", 1, "Dobra", "DOBRA1", op=f"OP-{i}") for i in range(1, total + 1)
        ]
        eventos.append(_event(900, "boa", 3, "Solda", "SOLDA1"))
        tree, overview = _tree(_EventRepo(eventos), "qtd.boa")

        self.assertEqual(tree["value"], total + 3)
        self.assertEqual(tree["value"], overview["production"]["good"])
        self.assertTrue(tree["truncated"])
        dobra = next(n for n in tree["children"] if n["label"] == "Dobra")
        resource = dobra["children"][0]
        self.assertTrue(resource["truncated"])
        self.assertEqual(resource["value"], float(total))
        real = [c for c in resource["children"] if not c["truncated"]]
        self.assertEqual(len(real), MAX_LEAVES_PER_RESOURCE)
        rest = next(c for c in resource["children"] if c["truncated"])
        self.assertEqual(rest["value"], 50.0)
        self.assertEqual(sum(c["value"] for c in resource["children"]), resource["value"])
        solda = next(n for n in tree["children"] if n["label"] == "Solda")
        self.assertFalse(solda["children"][0]["truncated"])
        self.assertTrue(tree["reconciliation"]["ok"])

    def test_sem_corte_nao_marca_truncated(self):
        tree, _ = _tree(_EventRepo(_events()), "qtd.boa")
        self.assertFalse(tree["truncated"])

    def test_fallback_usa_os_apontamentos_como_a_visao_geral_e_avisa(self):
        facts = [
            {
                "id": 11, "op": "OP-1", "tipo_setor": "Dobra", "maquina": "DOBRA1",
                "operador_inicio_nome": "Maria",
                "data_inicio": datetime(2026, 8, 19, 8, 0),
                "data_fim": datetime(2026, 8, 19, 9, 0),
                "quantidade_boa": 8, "quantidade_refugo": 1, "quantidade_retrabalho": 0,
                "eventos": [],
            },
            {
                "id": 12, "op": "OP-2", "tipo_setor": "Solda", "maquina": "SOLDA1",
                "data_inicio": datetime(2026, 8, 19, 10, 0),
                "data_fim": datetime(2026, 8, 19, 11, 0),
                "quantidade_boa": 6, "quantidade_refugo": 0, "quantidade_retrabalho": 2,
                "eventos": [],
            },
            {  # fora do período: o overview também ignora
                "id": 13, "op": "OP-3", "tipo_setor": "Solda", "maquina": "SOLDA1",
                "data_inicio": datetime(2026, 8, 25, 10, 0),
                "data_fim": datetime(2026, 8, 25, 11, 0),
                "quantidade_boa": 100, "quantidade_refugo": 0, "quantidade_retrabalho": 0,
                "eventos": [],
            },
        ]
        repo = _BaseRepo(facts=facts)
        for metric, key in (
            ("qtd.boa", "good"), ("qtd.refugo", "scrap"), ("qtd.retrabalho", "rework"),
        ):
            with self.subTest(metric):
                tree, overview = _tree(repo, metric)
                self.assertEqual(overview["production"]["source"], "apontamentos_operacionais_fallback")
                self.assertEqual(tree["value"], overview["production"][key])
                self.assertTrue(tree["reconciliation"]["ok"], tree["reconciliation"])
                self.assertTrue(any("mesma fonte" in note for note in tree["notes"]))
        tree, _ = _tree(repo, "qtd.boa")
        self.assertEqual(tree["value"], 14.0)
        leaf = next(_leaves(tree["children"]))
        self.assertEqual(leaf["detail"]["origem"], "apontamentos_operacionais")

    def test_fonte_de_eventos_nao_gera_aviso_de_fallback(self):
        tree, _ = _tree(_EventRepo(_events()), "qtd.boa")
        self.assertFalse(any("mesma fonte" in note for note in tree["notes"]))


class UnknownMetricTests(unittest.TestCase):
    def test_id_desconhecido_levanta_unknown_metric(self):
        service, _ = _service(_EventRepo([]))
        with self.assertRaises(UnknownMetricError):
            service.explain("qtd.inexistente", _filters())


class _ApiRepo(_ThreeDayOeeRepo):
    def listar_eventos_quantidade_periodo(self, inicio, fim, **_kwargs):
        rows = [
            {
                "id": 1, "tipo": "boa", "quantidade": 9, "op": "OP-1",
                "tipo_setor": "Dobra", "recurso": "DOBRA1", "operador": "Maria",
                "data_hora": datetime(2026, 8, 18, 8, 30), "origem": "gestor_pecas",
            },
            {
                "id": 2, "tipo": "refugo", "quantidade": 1, "op": "OP-1",
                "tipo_setor": "Dobra", "recurso": "DOBRA1", "operador": "Maria",
                "motivo": "Trinca",
                "data_hora": datetime(2026, 8, 19, 8, 30), "origem": "gestor_pecas",
            },
        ]
        return [row for row in rows if inicio <= row["data_hora"] <= fim]


def _user(role, *, management):
    return SessionUser(
        id=5, name=f"Conta {role}", role=role, management_access=management,
        andon_access=True, operator_access=not management,
    )


class ValueEndpointTests(unittest.TestCase):
    def setUp(self):
        db = _ApiRepo()
        self.app = create_app(settings=_settings(), database_factory=lambda: db)
        self.app.dependency_overrides[get_database] = lambda: db
        self.app.dependency_overrides[require_csrf] = lambda: None
        self.app.dependency_overrides[get_current_user] = lambda: _user("gestor", management=True)
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)
        self.facade = FrontendBackendFacade(db, now_func=lambda: AGORA)

    def _get(self, metric):
        return self.client.get(URL, params={"metric": metric, **PERIOD})

    def test_resposta_de_valor_e_igual_ao_overview_pela_api(self):
        production = self.client.get(OVERVIEW, params=PERIOD).json()["production"]
        for metric, key in (
            ("qtd.boa", "good"), ("qtd.refugo", "scrap"), ("qtd.retrabalho", "rework"),
        ):
            with self.subTest(metric):
                response = self._get(metric)
                self.assertEqual(response.status_code, 200, response.text)
                body = response.json()
                self.assertEqual(body["kind"], "value")
                self.assertEqual(body["value"], production[key])
                self.assertTrue(body["reconciliation"]["ok"])
        self.assertEqual(self._get("qtd.boa").json()["value"], 9)
        leaf = self._get("qtd.refugo").json()["children"][0]["children"][0]["children"][0]
        self.assertEqual(leaf["detail"]["operador"], "Maria")
        self.assertEqual(leaf["detail"]["motivo"], "Trinca")

    def test_tempo_continua_respondendo_como_antes(self):
        body = self._get("tempo.producao").json()
        self.assertIn("total_seconds", body)
        self.assertNotIn("kind", body)

    def test_id_desconhecido_422_em_qualquer_prefixo(self):
        for metric in ("qtd.inexistente", "qld.qualquer", "naoexiste"):
            with self.subTest(metric):
                response = self._get(metric)
                self.assertEqual(response.status_code, 422)
                self.assertEqual(response.json()["code"], "unknown_metric")

    def test_operador_oculto_para_quem_nao_e_gestao(self):
        gestor = explain_for_user(
            self.facade, "qtd.refugo", _filters(), _user("gestor", management=True)
        )
        outro = explain_for_user(
            self.facade, "qtd.refugo", _filters(), _user("operador_dobra", management=False)
        )
        gestor_leaf = next(_leaves(gestor["children"]))
        outro_leaf = next(_leaves(outro["children"]))
        self.assertEqual(gestor_leaf["detail"]["operador"], "Maria")
        self.assertIsNone(outro_leaf["detail"]["operador"])
        self.assertEqual(outro_leaf["detail"]["motivo"], "Trinca")

    def test_chat_ia_recebe_o_contexto_de_valor(self):
        tree = explain_for_user(
            self.facade, "qtd.refugo", _filters(), _user("gestor", management=True)
        )
        context = build_explanation_context(tree, max_tokens=4000)
        self.assertIn("Valor: 1 peça", context)
        self.assertIn("Trinca", context)
        self.assertNotIn("Total:", context)

    def test_chat_ia_taxa_mostra_pecas_sem_percentual_nas_entradas_e_excluidos(self):
        tree = {
            "kind": "value", "metric": "qtd.taxa_refugo", "label": "Taxa de refugo",
            "unit": "pct", "value": 4.8, "reason": "x", "rule": "y",
            "children": [
                {"kind": "input", "label": "Refugo", "value": 12, "children": [], "detail": None, "truncated": False},
                {"kind": "input", "label": "Boa + refugo", "value": 250, "children": [], "detail": None, "truncated": False},
            ],
            "excluded": [{"label": "Retrabalho", "value": 4, "reason": "Não conta como refugo."}],
            "reconciliation": {"ok": True, "sum": 4.8, "diff": 0},
            "calculated_at": "2026-10-19T10:00:00", "truncated": False, "notes": [],
        }
        context = build_explanation_context(tree, max_tokens=4000)
        self.assertIn("Valor: 4,8%", context.replace(".", ","))
        self.assertIn('"Refugo": 12', context)
        self.assertIn('"Retrabalho": 4.', context)
        self.assertNotIn("12%", context)
        self.assertNotIn("250%", context)
        self.assertNotIn("4%", context.replace("4,8%", "").replace("4.8%", ""))


class AdversarialBorderTests(unittest.TestCase):
    """Casos de borda: o value tem que continuar sendo o número da Visão Geral."""

    def _assert_closes(self, repo, metric, key=None):
        tree, overview = _tree(repo, metric)
        if key:
            self.assertEqual(tree["value"], overview["production"][key], metric)
        self.assertTrue(tree["reconciliation"]["ok"], (metric, tree["reconciliation"]))
        return tree, overview

    def test_periodo_vazio_com_fonte_de_eventos_nao_inventa_nada(self):
        for metric, key in (("qtd.boa", "good"), ("qtd.refugo", "scrap"), ("qtd.retrabalho", "rework")):
            with self.subTest(metric):
                tree, overview = self._assert_closes(_EventRepo([]), metric, key)
                self.assertEqual((tree["value"], tree["children"], tree["excluded"]), (0.0, [], []))
                self.assertFalse(tree["truncated"])
                self.assertEqual(tree["reason"], overview["production"]["reason"])

    def test_periodo_vazio_no_fallback_avisa_a_fonte_e_fecha(self):
        tree, overview = self._assert_closes(_BaseRepo(), "qtd.boa", "good")
        self.assertEqual(overview["production"]["source"], "apontamentos_operacionais_fallback")
        self.assertEqual(tree["children"], [])
        self.assertTrue(any("mesma fonte" in note for note in tree["notes"]))

    def test_so_corte_sem_nenhum_lancamento_de_quantidade(self):
        repo = _EventRepo([], cutting=[_cutting_row(qtd=7), _cutting_row(op="OP-10", qtd=3, maquina="LASER2")])
        tree, overview = self._assert_closes(repo, "qtd.boa", "good")
        self.assertEqual(tree["value"], 10.0)
        self.assertEqual([(n["label"], n["value"]) for n in tree["children"]], [("Corte", 10.0)])
        leaf = next(_leaves(tree["children"]))
        self.assertEqual(leaf["kind"], "op")
        self.assertEqual(leaf["detail"]["origem"], "apontamentos_corte")
        self.assertTrue(any("Corte" in note for note in tree["notes"]))
        # Sem refugo/retrabalho: taxa 0 (não "indisponível") e FTT 100.
        rate, _ = self._assert_closes(repo, "qtd.taxa_refugo")
        self.assertEqual(rate["value"], 0.0)
        ftt, overview = self._assert_closes(repo, "qtd.ftt")
        self.assertEqual(ftt["value"], overview["kpis"]["ftt"]["value"])
        self.assertAlmostEqual(ftt["value"], 100.0)

    def test_corte_sem_op_ou_sem_quantidade_fica_fora_como_na_visao_geral(self):
        cutting = [
            _cutting_row(qtd=5),
            _cutting_row(op="", qtd=50),
            _cutting_row(op="OP-8", qtd=0),
            _cutting_row(op="OP-7", qtd=-4),
        ]
        tree, _ = self._assert_closes(_EventRepo([], cutting=cutting), "qtd.boa", "good")
        self.assertEqual(tree["value"], 5.0)
        self.assertEqual(len(list(_leaves(tree["children"]))), 1)

    def test_corte_com_fallback_soma_apontamentos_e_corte(self):
        facts = [{
            "id": 11, "op": "OP-1", "tipo_setor": "Dobra", "maquina": "DOBRA1",
            "data_inicio": datetime(2026, 8, 19, 8, 0), "data_fim": datetime(2026, 8, 19, 9, 0),
            "quantidade_boa": 8, "quantidade_refugo": 0, "quantidade_retrabalho": 0, "eventos": [],
        }]
        tree, overview = self._assert_closes(_BaseRepo(facts=facts, cutting=[_cutting_row(qtd=4)]), "qtd.boa", "good")
        self.assertEqual(overview["production"]["source"], "apontamentos_operacionais_fallback")
        self.assertEqual({n["label"]: n["value"] for n in tree["children"]}, {"Dobra": 8.0, "Corte": 4.0})

    def test_tipo_com_caixa_e_espacos_conta_como_o_overview_e_desconhecido_fica_de_fora(self):
        eventos = [
            _event(1, "BOA ", 4, "Dobra", "DOBRA1"),
            _event(2, " Refugo", 1, "Dobra", "DOBRA1"),
            _event(3, None, 6, "Dobra", "DOBRA1"),
            _event(4, "", 2, "Dobra", "DOBRA1"),
            _event(5, "scrap", 9, "Dobra", "DOBRA1"),
        ]
        repo = _EventRepo(eventos)
        for metric, key, expected in (("qtd.boa", "good", 4.0), ("qtd.refugo", "scrap", 1.0)):
            with self.subTest(metric):
                tree, _ = self._assert_closes(repo, metric, key)
                self.assertEqual(tree["value"], expected)
        tree, _ = self._assert_closes(repo, "qtd.boa")
        unknown = next(x for x in tree["excluded"] if "desconhecido" in x["label"])
        self.assertEqual(unknown["value"], 17.0)

    def test_evento_sem_setor_recurso_ou_op_usa_rotulos_honestos(self):
        evento = _event(1, "refugo", 3, "", "", op="")
        evento["tipo_setor"] = None
        evento["recurso"] = None
        tree, _ = self._assert_closes(_EventRepo([evento]), "qtd.refugo", "scrap")
        sector = tree["children"][0]
        resource = sector["children"][0]
        leaf = resource["children"][0]
        self.assertEqual((sector["label"], resource["label"]), ("Não informado", "Sem recurso informado"))
        self.assertTrue(leaf["label"].startswith("Sem OP"))
        self.assertNotIn("op", leaf["detail"])

    def test_refugo_sem_motivo_nao_ganha_motivo_nem_quebra_a_soma(self):
        eventos = [
            _event(1, "refugo", 2, "Dobra", "DOBRA1", motivo=None),
            _event(2, "refugo", 3, "Dobra", "DOBRA1", motivo="   "),
            _event(3, "refugo", 4, "Dobra", "DOBRA1", motivo="Trinca"),
        ]
        tree, _ = self._assert_closes(_EventRepo(eventos), "qtd.refugo", "scrap")
        leaves = list(_leaves(tree["children"]))
        self.assertEqual(sorted(leaf["value"] for leaf in leaves), [2.0, 3.0, 4.0])
        self.assertEqual(sum("motivo" in leaf["detail"] for leaf in leaves), 1)

    def test_mesmo_recurso_com_caixa_diferente_vira_um_no_so(self):
        eventos = [_event(1, "boa", 2, "Dobra", "Dobra1"), _event(2, "boa", 3, "Dobra", "DOBRA1")]
        tree, _ = self._assert_closes(_EventRepo(eventos), "qtd.boa", "good")
        self.assertEqual(len(tree["children"][0]["children"]), 1)
        self.assertEqual(tree["children"][0]["children"][0]["value"], 5.0)

    def test_divisao_por_zero_das_taxas(self):
        so_retrabalho = _EventRepo([_event(1, "retrabalho", 5, "Solda", "SOLDA1")])
        rate, _ = self._assert_closes(so_retrabalho, "qtd.taxa_refugo")
        self.assertIsNone(rate["value"])
        self.assertIsNone(rate["reconciliation"]["sum"])
        self.assertEqual([x["label"] for x in rate["excluded"]], ["Retrabalho"])
        # FTT = 0 é um número válido (não pode virar "indisponível").
        ftt, overview = self._assert_closes(so_retrabalho, "qtd.ftt")
        self.assertEqual(ftt["value"], 0.0)
        self.assertIsNotNone(ftt["value"])
        self.assertEqual(ftt["value"], overview["kpis"]["ftt"]["value"])
        # Sem nenhuma peça: os dois ficam None, com motivo, e as entradas são zero.
        for metric in ("qtd.taxa_refugo", "qtd.ftt"):
            tree, _ = self._assert_closes(_EventRepo([]), metric)
            self.assertIsNone(tree["value"])
            self.assertTrue(tree["reason"])
            self.assertEqual([c["value"] for c in tree["children"]], [0.0] * len(tree["children"]))

    def test_taxa_de_refugo_so_com_refugo_e_100_por_cento(self):
        tree, _ = self._assert_closes(_EventRepo([_event(1, "refugo", 3, "Dobra", "DOBRA1")]), "qtd.taxa_refugo")
        self.assertAlmostEqual(tree["value"], 100.0)

    def test_sem_lancamento_do_tipo_nao_diz_que_nao_ha_registro_quando_ha_outro_tipo(self):
        repo = _EventRepo([_event(1, "boa", 5, "Dobra", "DOBRA1")])
        tree, overview = self._assert_closes(repo, "qtd.refugo", "scrap")
        self.assertIsNone(overview["production"]["reason"])
        self.assertEqual(tree["children"], [])
        self.assertIn("refugo", tree["reason"].lower())
        self.assertNotIn("Nenhum registro de quantidade", tree["reason"])


class AdversarialTruncationTests(unittest.TestCase):
    def _boas(self, count, setor="Dobra", recurso="DOBRA1"):
        return [_event(i, "boa", 1, setor, recurso, op=f"OP-{i}") for i in range(1, count + 1)]

    def test_limite_exato_nao_trunca_e_um_a_mais_trunca_com_rotulo_no_singular(self):
        exato, _ = _tree(_EventRepo(self._boas(MAX_LEAVES_PER_RESOURCE)), "qtd.boa")
        self.assertFalse(exato["truncated"])
        self.assertEqual(len(exato["children"][0]["children"][0]["children"]), MAX_LEAVES_PER_RESOURCE)

        mais_um, overview = _tree(_EventRepo(self._boas(MAX_LEAVES_PER_RESOURCE + 1)), "qtd.boa")
        self.assertTrue(mais_um["truncated"])
        self.assertEqual(mais_um["value"], overview["production"]["good"])
        self.assertTrue(mais_um["reconciliation"]["ok"])
        rest = mais_um["children"][0]["children"][0]["children"][-1]
        self.assertTrue(rest["truncated"])
        self.assertEqual((rest["value"], rest["label"]), (1.0, "Outro registro"))

    def test_cada_recurso_trunca_sozinho_e_o_setor_continua_somando_certo(self):
        eventos = self._boas(MAX_LEAVES_PER_RESOURCE + 5, recurso="DOBRA1") + [
            _event(10_000 + i, "boa", 2, "Dobra", "DOBRA2") for i in range(3)
        ]
        tree, overview = _tree(_EventRepo(eventos), "qtd.boa")
        recursos = {r["label"]: r for r in tree["children"][0]["children"]}
        self.assertTrue(recursos["DOBRA1"]["truncated"])
        self.assertFalse(recursos["DOBRA2"]["truncated"])
        self.assertEqual(tree["children"][0]["value"], MAX_LEAVES_PER_RESOURCE + 5 + 6)
        self.assertEqual(tree["value"], overview["production"]["good"])
        self.assertTrue(tree["reconciliation"]["ok"])

    def test_corte_acima_do_limite_tambem_trunca_sem_perder_pecas(self):
        cutting = [_cutting_row(op=f"OP-{i}", qtd=2) for i in range(1, MAX_LEAVES_PER_RESOURCE + 31)]
        tree, overview = _tree(_EventRepo([], cutting=cutting), "qtd.boa")
        self.assertTrue(tree["truncated"])
        self.assertEqual(tree["value"], overview["production"]["good"])
        self.assertEqual(tree["children"][0]["value"], tree["value"])
        self.assertTrue(tree["reconciliation"]["ok"])

    def test_truncamento_chega_ao_contexto_da_ia(self):
        tree, _ = _tree(_EventRepo(self._boas(MAX_LEAVES_PER_RESOURCE + 10)), "qtd.boa")
        context = build_explanation_context(tree, max_tokens=8000)
        self.assertIn("TRUNCATED", context)
        self.assertIn("Valor: 210 peças", context)

    def test_max_leaves_reduzido_mantem_a_conta(self):
        service, management = _service(_EventRepo(self._boas(12)))
        tree = service.explain("qtd.boa", _filters(), max_leaves=5).to_dict()
        self.assertTrue(tree["truncated"])
        self.assertEqual(tree["value"], management.get_overview(_filters())["production"]["good"])
        self.assertTrue(tree["reconciliation"]["ok"])


class AdversarialContextAndApiTests(unittest.TestCase):
    def test_contexto_da_ia_nao_mostra_quantidade_como_percentual(self):
        repo = _EventRepo(_events(), cutting=[_cutting_row()])
        tree, _ = _tree(repo, "qtd.taxa_refugo")
        context = build_explanation_context(tree, max_tokens=4000)
        self.assertIn('"Peças boas": 28', context)
        self.assertNotIn('"Peças boas": 28%', context)
        self.assertNotIn('"Refugo": 2%', context)
        self.assertNotIn('"Retrabalho": 3%', context)
        self.assertIn('"Retrabalho": 3.', context)
        self.assertIn("Valor: 6,7%", context)

    def test_contexto_da_ia_do_ftt_tambem_usa_quantidades_nas_entradas(self):
        tree, _ = _tree(_EventRepo(_events()), "qtd.ftt")
        context = build_explanation_context(tree, max_tokens=4000)
        self.assertIn('"Retrabalho": 3', context)
        # O único "%" do contexto é o do próprio FTT; as entradas ficam em peças.
        self.assertIn("Valor: 78,3%", context)
        self.assertEqual(context.count("%"), 1)

    def test_operador_nao_vaza_no_contexto_da_ia_nem_no_fallback(self):
        db = _ApiRepo()
        facade = FrontendBackendFacade(db, now_func=lambda: AGORA)
        # Só o refugo tem lançamento de Maria dentro do período; o fallback cobre as boas.
        for metric in ("qtd.refugo",):
            with self.subTest(metric):
                gestor = build_explanation_context(
                    explain_for_user(facade, metric, _filters(), _user("gestor", management=True)),
                    max_tokens=4000,
                )
                operador = build_explanation_context(
                    explain_for_user(facade, metric, _filters(), _user("operador_dobra", management=False)),
                    max_tokens=4000,
                )
                self.assertIn("Maria", gestor)
                self.assertNotIn("Maria", operador)
        facts = [{
            "id": 1, "op": "OP-1", "tipo_setor": "Dobra", "maquina": "DOBRA1",
            "operador_inicio_nome": "Joana", "data_inicio": datetime(2026, 8, 19, 8, 0),
            "data_fim": datetime(2026, 8, 19, 9, 0), "quantidade_boa": 5,
            "quantidade_refugo": 0, "quantidade_retrabalho": 0, "eventos": [],
        }]
        fallback = FrontendBackendFacade(_BaseRepo(facts=facts), now_func=lambda: AGORA)
        gestor = explain_for_user(fallback, "qtd.boa", _filters(), _user("gestor", management=True))
        operador = explain_for_user(fallback, "qtd.boa", _filters(), _user("operador_dobra", management=False))
        self.assertIn("Joana", str(gestor))
        self.assertNotIn("Joana", str(operador))

    def test_excluidos_de_taxa_vem_em_quantidade(self):
        tree, _ = _tree(_EventRepo(_events()), "qtd.taxa_refugo")
        self.assertEqual(tree["excluded"][0]["value"], 3.0)
        self.assertEqual(tree["unit"], "pct")


class _FilterableApiRepo(_ApiRepo):
    """Como ``_ApiRepo``, mas respeita os filtros setor/recurso (como o repositório real)."""

    def listar_eventos_quantidade_periodo(self, inicio, fim, **kwargs):
        rows = super().listar_eventos_quantidade_periodo(inicio, fim)
        setor, recurso = kwargs.get("setor"), kwargs.get("recurso")
        return [
            row for row in rows
            if (not setor or row["tipo_setor"] == setor) and (not recurso or row["recurso"] == recurso)
        ]


class AdversarialEndpointTests(unittest.TestCase):
    def setUp(self):
        db = _FilterableApiRepo()
        self.app = create_app(settings=_settings(), database_factory=lambda: db)
        self.app.dependency_overrides[get_database] = lambda: db
        self.app.dependency_overrides[require_csrf] = lambda: None
        self.user = _user("gestor", management=True)
        self.app.dependency_overrides[get_current_user] = lambda: self.user
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)

    def _get(self, metric, **extra):
        return self.client.get(URL, params={"metric": metric, **PERIOD, **extra})

    def test_ids_invalidos_dao_422_sem_500(self):
        for metric in ("qtd.", "qtd", "qtd.boa.extra", "QTD.boa", "qtd.BOA", " ", "qtd. boa", "qtd.taxa", "tempo.", "x" * 64):
            with self.subTest(metric):
                response = self._get(metric)
                self.assertEqual(response.status_code, 422, response.text)
                self.assertEqual(response.json()["code"], "unknown_metric")

    def test_id_vazio_ou_longo_demais_e_rejeitado_na_validacao(self):
        self.assertEqual(self.client.get(URL, params={"metric": "", **PERIOD}).status_code, 422)
        self.assertEqual(self.client.get(URL, params=PERIOD).status_code, 422)
        self.assertEqual(self._get("qtd." + "a" * 80).status_code, 422)

    def test_espacos_nas_pontas_do_id_sao_aceitos_como_no_tempo(self):
        response = self._get("  qtd.boa ")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["metric"], "qtd.boa")

    def test_tempo_continua_sem_campo_kind_e_com_o_mesmo_formato(self):
        response = self._get("tempo.producao")
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertNotIn("kind", body)
        self.assertIn("total_seconds", body)
        self.assertNotIn("unit", body)

    def test_valor_pela_api_com_filtros_e_igual_ao_overview_dos_mesmos_filtros(self):
        for extra in ({}, {"setor": "Dobra"}, {"recurso": "DOBRA1"}, {"setor": "Solda"}):
            overview = self.client.get(OVERVIEW, params={**PERIOD, **extra}).json()["production"]
            for metric, key in (("qtd.boa", "good"), ("qtd.refugo", "scrap"), ("qtd.retrabalho", "rework")):
                with self.subTest(extra=extra, metric=metric):
                    body = self._get(metric, **extra).json()
                    self.assertEqual(body["value"], overview[key])
                    self.assertTrue(body["reconciliation"]["ok"], body["reconciliation"])

    def test_taxa_sem_pecas_serializa_none_como_null(self):
        response = self._get("qtd.taxa_refugo", inicio="2026-01-01T00:00:00", fim="2026-01-02T00:00:00")
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertIsNone(body["value"])
        self.assertEqual(body["unit"], "pct")
        self.assertTrue(body["reconciliation"]["ok"])

    def test_quem_nao_e_gestao_nao_acessa_nem_ve_operador(self):
        self.user = _user("operador_dobra", management=False)
        response = self._get("qtd.refugo")
        self.assertIn(response.status_code, (401, 403))
        self.assertNotIn("Maria", response.text)


if __name__ == "__main__":
    unittest.main()
