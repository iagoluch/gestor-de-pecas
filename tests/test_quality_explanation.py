"""Explicação de valor ``qld.*``: Análises > Qualidade e Alertas/Auditoria.

Contrato: ``docs/superpowers/specs/2026-10-19-explicacao-valor-contrato.md``.
A explicação só explica: o ``value`` é o número da tela (``quality()["totals"]``
ou ``run_period()["count"/"by_severity"]``) e a árvore fecha com ele.
"""

from __future__ import annotations

import unittest
from datetime import datetime

from fastapi.testclient import TestClient

from backend.api.database import get_database
from backend.api.dependencies.auth import get_current_user, require_csrf
from backend.api.main import create_app
from backend.api.routers.explanation import explain_for_user
from mes.ai.explanation_context import build_explanation_context
from mes.contracts import AnalyticsFilter
from mes.services.frontend_facade import FrontendBackendFacade
from mes.services.metric_explanation import UnknownMetricError
from mes.services.quality_explanation import QualityExplanationService
from mes.services.value_explanation import MAX_LEAVES_PER_RESOURCE
from tests.test_standard_time import _settings
from tests.test_value_explanation import (
    AGORA,
    DIA,
    PERIOD,
    URL,
    _ApiRepo,
    _BaseRepo,
    _cutting_row,
    _event,
    _EventRepo,
    _events,
    _leaves,
    _user,
)


def _filters(**extra):
    return AnalyticsFilter(DIA, DIA.replace(hour=23, minute=59), **extra)


class _SectorEventRepo(_EventRepo):
    """Fonte de eventos que respeita o filtro de setor, como o SQL real."""

    def listar_eventos_quantidade_periodo(self, *_a, setor=None, **_k):
        return [
            dict(row) for row in self._events
            if setor is None or row.get("tipo_setor") == setor
        ]


def _facade(repo):
    return FrontendBackendFacade(repo, now_func=lambda: AGORA)


def _explain(repo, metric, filters=None, **kwargs):
    facade = _facade(repo)
    service = QualityExplanationService(facade.analytics, facade.audit_service)
    return service.explain(metric, filters or _filters(), **kwargs).to_dict()


def _sum_leaves(tree):
    return sum(leaf["value"] for leaf in _leaves(tree["children"]))


class _StubAudit:
    """Auditoria com lista de issues controlada (bordas que o SQL não produz fácil)."""

    def __init__(self, issues, *, source="eventos_estado_recurso", gaps=0):
        self.issues = issues
        self.source = source
        self.gaps = gaps

    def _now(self):
        return AGORA

    def run_period(self, filters):
        severity = {"info": 0, "aviso": 0, "erro": 0, "critico": 0}
        for issue in self.issues:
            severity[issue["severity"]] = severity.get(issue["severity"], 0) + 1
        return {
            "issues": list(self.issues),
            "count": len(self.issues),
            "by_severity": severity,
            "diagnostics": {"calendar_gap_count": self.gaps},
            "physical_state_source": self.source,
            "reliability_percentage": None,
        }


def _issue(severity="critico", type_="intervalo_invalido", resource="DOBRA1", **extra):
    return {
        "type": type_,
        "severity": severity,
        "message": "Fim do apontamento anterior ao início.",
        "appointment_id": extra.pop("appointment_id", 1),
        "op": extra.pop("op", "OP-1"),
        "operation": extra.pop("operation", "010"),
        "resource": resource,
        "sector": extra.pop("sector", "Dobra"),
        **extra,
    }


def _stub_tree(issues, metric, filters=None, **kwargs):
    service = QualityExplanationService(None, _StubAudit(issues, **kwargs), now_func=lambda: AGORA)
    return service.explain(metric, filters or _filters()).to_dict()


# --------------------------------------------------------------- Qualidade


class QualityTotalsTests(unittest.TestCase):
    def test_valor_e_arvore_fecham_com_quality_totals(self):
        repo = _EventRepo(_events())
        totals = _facade(repo).analytics.quality(_filters())["totals"]
        for metric, kind in (("qld.boa", "boa"), ("qld.refugo", "refugo"), ("qld.retrabalho", "retrabalho")):
            with self.subTest(metric):
                tree = _explain(repo, metric)
                self.assertEqual(tree["kind"], "value")
                self.assertEqual(tree["unit"], "pcs")
                self.assertEqual(tree["value"], totals[kind])
                self.assertEqual(_sum_leaves(tree), tree["value"])
                self.assertTrue(tree["reconciliation"]["ok"])
                self.assertEqual(tree["reconciliation"]["diff"], 0.0)
        self.assertEqual(totals, {"boa": 18, "refugo": 2, "retrabalho": 3})

    def test_arvore_setor_recurso_evento_com_detalhe_e_operador(self):
        evento = _event(
            4, "refugo", 2, "Dobra", "DOBRA1", motivo="Trinca", op="OP-1",
            numero_operacao="020", produto_codigo="P-9",
        )
        tree = _explain(_EventRepo([evento]), "qld.refugo")
        sector = tree["children"][0]
        resource = sector["children"][0]
        leaf = resource["children"][0]
        self.assertEqual([sector["kind"], resource["kind"], leaf["kind"]], ["sector", "resource", "event"])
        self.assertEqual(leaf["label"], "OP OP-1 · 19/08 10:00")
        self.assertEqual(leaf["detail"], {
            "id": 4, "op": "OP-1", "operacao": "020", "produto": "P-9",
            "operador": "Maria", "data_hora": "2026-08-19T10:00:00",
            "motivo": "Trinca", "origem": "gestor_pecas",
        })
        self.assertIn("Por motivo: Trinca: 2 peças.", tree["notes"])

    def test_boa_diverge_da_visao_geral_quando_ha_corte(self):
        repo = _EventRepo(_events(), cutting=[_cutting_row(qtd=10)])
        facade = _facade(repo)
        tree = _explain(repo, "qld.boa")
        overview_good = facade.management.get_overview(_filters())["production"]["good"]
        self.assertEqual(tree["value"], 18)
        self.assertEqual(overview_good, 28)
        self.assertTrue(any("Corte" in note and "Visão Geral" in note for note in tree["notes"]))
        self.assertTrue(any("28" in note and "18" in note for note in tree["notes"]))
        # O Corte não entra na árvore: ela fecha com a tela de Qualidade, não com a Visão Geral.
        self.assertNotIn("Corte", [node["label"] for node in tree["children"]])
        self.assertTrue(tree["reconciliation"]["ok"])

    def test_filtro_de_setor_reconcilia_com_a_linha_do_setor(self):
        eventos = _events() + [_event(9, "refugo", 4, "Solda", "SOLDA1", motivo="Poro")]
        repo = _SectorEventRepo(eventos)
        by_sector = {
            row["setor"]: row
            for row in _facade(repo).analytics.quality(_filters())["by_sector"]
        }
        tree = _explain(repo, "qld.refugo", _filters(setor="Solda"))
        self.assertEqual(tree["value"], by_sector["Solda"]["refugo"])
        self.assertEqual(tree["value"], 4)
        self.assertEqual([node["label"] for node in tree["children"]], ["Solda"])
        self.assertTrue(tree["reconciliation"]["ok"])

    def test_motivo_ausente_vira_nao_informado_sem_inventar_chave(self):
        repo = _EventRepo([
            _event(1, "retrabalho", 2, "Solda", "SOLDA1", motivo=None),
            _event(2, "retrabalho", 1, "Solda", "SOLDA1", motivo="Rebarba"),
        ])
        tree = _explain(repo, "qld.retrabalho")
        self.assertIn("Por motivo: Não informado: 2 peças; Rebarba: 1 peça.", tree["notes"])
        sem_motivo = next(leaf for leaf in _leaves(tree["children"]) if leaf["value"] == 2.0)
        self.assertNotIn("motivo", sem_motivo["detail"])
        # Retrabalho parcial: o aviso do próprio payload da tela.
        self.assertTrue(any("Retrabalho permanecerá parcial" in note for note in tree["notes"]))

    def test_fallback_sem_fonte_de_eventos_avisa_e_fecha(self):
        facts = [{
            "id": 7, "op": "OP-7", "maquina": "DOBRA1", "tipo_setor": "Dobra",
            "status": "Finalizado", "quantidade_boa": 5, "quantidade_refugo": 1,
            "data_inicio": datetime(2026, 8, 19, 8), "data_fim": datetime(2026, 8, 19, 9),
        }]
        repo = _BaseRepo(facts=facts)
        totals = _facade(repo).analytics.quality(_filters())["totals"]
        tree = _explain(repo, "qld.boa")
        self.assertEqual(tree["value"], totals["boa"])
        self.assertEqual(tree["value"], 5)
        self.assertTrue(tree["reconciliation"]["ok"])
        self.assertTrue(any("fonte reserva" in note for note in tree["notes"]))

    def test_periodo_vazio(self):
        tree = _explain(_EventRepo([]), "qld.refugo")
        self.assertEqual(tree["value"], 0.0)
        self.assertEqual(tree["children"], [])
        self.assertTrue(tree["reconciliation"]["ok"])

    def test_tipo_desconhecido_e_quantidade_negativa_vao_para_excluidos(self):
        repo = _EventRepo([
            _event(1, "boa", 5, "Dobra", "DOBRA1"),
            _event(2, "boa", -3, "Dobra", "DOBRA1"),
            _event(3, "sucata", 7, "Dobra", "DOBRA1"),
        ])
        tree = _explain(repo, "qld.boa")
        self.assertEqual(tree["value"], 5)
        self.assertTrue(tree["reconciliation"]["ok"])
        labels = {item["label"]: item["value"] for item in tree["excluded"]}
        self.assertEqual(labels["Lançamentos de tipo desconhecido (1)"], 7.0)
        self.assertEqual(labels["Lançamentos com quantidade zero ou negativa (1)"], 0.0)

    def test_corte_de_200_folhas_por_recurso_com_total_certo(self):
        eventos = [
            _event(i, "refugo", 1, "Dobra", "DOBRA1", hora=8 + i % 10)
            for i in range(MAX_LEAVES_PER_RESOURCE + 5)
        ]
        tree = _explain(_EventRepo(eventos), "qld.refugo")
        resource = tree["children"][0]["children"][0]
        self.assertEqual(len(resource["children"]), MAX_LEAVES_PER_RESOURCE + 1)
        self.assertEqual(resource["children"][-1]["label"], "Outros 5 registros")
        self.assertTrue(resource["truncated"])
        self.assertTrue(tree["truncated"])
        self.assertEqual(tree["value"], MAX_LEAVES_PER_RESOURCE + 5)
        self.assertTrue(tree["reconciliation"]["ok"])


# --------------------------------------------------------------- Auditoria


def _audit_facts():
    return [
        {   # erro: finalizado sem peça boa
            "id": 1, "status": "Finalizado", "quantidade_boa": 0, "maquina": "DOBRA1",
            "tipo_setor": "Dobra", "op": "OP-1", "operador_inicio": 3,
            "data_inicio": datetime(2026, 8, 19, 8), "data_fim": datetime(2026, 8, 19, 9),
        },
        {   # crítico (sem recurso) + erro (sem operador) + crítico (fim < início)
            "id": 2, "status": "Em processo", "quantidade_boa": 0, "maquina": "",
            "tipo_setor": "Solda", "op": "OP-2", "operador_inicio": None,
            "data_inicio": datetime(2026, 8, 19, 11), "data_fim": datetime(2026, 8, 19, 10),
        },
    ]


class AuditTotalsTests(unittest.TestCase):
    def test_valor_igual_ao_run_period_da_tela_e_reconcilia(self):
        repo = _BaseRepo(facts=_audit_facts())
        screen = _facade(repo).auditoria(_filters())
        self.assertGreater(screen["count"], 0)
        for metric, key in (
            ("qld.auditoria.total", None),
            ("qld.auditoria.critico", "critico"),
            ("qld.auditoria.erro", "erro"),
            ("qld.auditoria.aviso", "aviso"),
        ):
            with self.subTest(metric):
                tree = _explain(repo, metric)
                expected = screen["count"] if key is None else screen["by_severity"][key]
                self.assertEqual(tree["unit"], "count")
                self.assertEqual(tree["value"], expected)
                self.assertEqual(_sum_leaves(tree), expected)
                self.assertTrue(tree["reconciliation"]["ok"])

    def test_total_e_a_soma_das_tres_gravidades(self):
        issues = [
            _issue("critico"), _issue("critico", resource="SOLDA1"),
            _issue("erro", "op_sem_operador"), _issue("aviso", "outro_tipo"),
        ]
        tree = _stub_tree(issues, "qld.auditoria.total")
        partes = {
            metric: _stub_tree(issues, metric)["value"]
            for metric in ("qld.auditoria.critico", "qld.auditoria.erro", "qld.auditoria.aviso")
        }
        self.assertEqual(tree["value"], 4)
        self.assertEqual(sum(partes.values()), tree["value"])
        self.assertEqual(
            [(node["kind"], node["label"], node["value"]) for node in tree["children"]],
            [("group", "Críticos", 2.0), ("group", "Erros", 1.0), ("group", "Atenções", 1.0)],
        )
        # gravidade -> tipo -> recurso -> registro
        critico = tree["children"][0]
        tipo = critico["children"][0]
        self.assertEqual((tipo["kind"], tipo["label"]), ("group", "Fim antes do início"))
        self.assertEqual(tipo["children"][0]["kind"], "resource")
        self.assertEqual(tipo["children"][0]["children"][0]["kind"], "event")

    def test_folha_tem_so_campos_existentes(self):
        issue = _issue(start=datetime(2026, 8, 19, 9, 30), end=datetime(2026, 8, 19, 9, 0),
                       seconds=0.0, source="regra_manufatura")
        tree = _stub_tree([issue], "qld.auditoria.critico")
        leaf = next(_leaves(tree["children"]))
        self.assertEqual(leaf["value"], 1.0)
        self.assertEqual(leaf["label"], "OP OP-1 · 19/08 09:30")
        self.assertEqual(leaf["detail"], {
            "mensagem": "Fim do apontamento anterior ao início.",
            "severidade": "critico", "apontamento": 1, "op": "OP-1", "operacao": "010",
            "setor": "Dobra", "inicio": "2026-08-19T09:30:00", "fim": "2026-08-19T09:00:00",
            "segundos": 0.0, "fonte": "regra_manufatura",
        })
        self.assertNotIn("operador", leaf["detail"])

    def test_notas_obrigatorias(self):
        tree = _stub_tree([_issue()], "qld.auditoria.total",
                          source="timeline_apontamentos_fallback", gaps=3)
        notes = " | ".join(tree["notes"])
        self.assertIn("confiabilidade", notes)
        self.assertIn("Lacunas de calendário", notes)
        self.assertIn("Neste período foram 3.", notes)
        self.assertIn("rateio", notes)
        self.assertIn("fonte reserva", notes)
        self.assertIn("200 linhas", notes)
        com_op = _stub_tree([_issue()], "qld.auditoria.total", filters=_filters(op="OP-1"))
        self.assertTrue(any("não roda" in note for note in com_op["notes"]))
        sem_fallback = _stub_tree([_issue()], "qld.auditoria.total")
        self.assertFalse(any("fonte reserva" in note for note in sem_fallback["notes"]))

    def test_mais_de_200_diz_o_total(self):
        issues = [_issue(resource=f"R{i}") for i in range(205)]
        tree = _stub_tree(issues, "qld.auditoria.total")
        self.assertTrue(any("205 no total" in note for note in tree["notes"]))

    def test_corte_de_200_registros_por_recurso(self):
        issues = [_issue(appointment_id=i) for i in range(MAX_LEAVES_PER_RESOURCE + 3)]
        tree = _stub_tree(issues, "qld.auditoria.critico")
        resource = tree["children"][0]["children"][0]
        self.assertEqual(len(resource["children"]), MAX_LEAVES_PER_RESOURCE + 1)
        self.assertEqual(resource["children"][-1]["label"], "Outros 3 registros")
        self.assertTrue(tree["truncated"])
        self.assertEqual(tree["value"], MAX_LEAVES_PER_RESOURCE + 3)
        self.assertTrue(tree["reconciliation"]["ok"])

    def test_periodo_vazio(self):
        for metric in ("qld.auditoria.total", "qld.auditoria.critico"):
            with self.subTest(metric):
                tree = _stub_tree([], metric)
                self.assertEqual(tree["value"], 0.0)
                self.assertEqual(tree["children"], [])
                self.assertTrue(tree["reconciliation"]["ok"])
                self.assertIn("Nenhuma inconsistência", tree["reason"])


class AuditAdversarialTests(unittest.TestCase):
    def test_sem_recurso_e_sem_setor(self):
        issue = _issue(resource=None, sector=None, op=None, appointment_id=None)
        tree = _stub_tree([issue], "qld.auditoria.critico")
        resource = tree["children"][0]["children"][0]
        self.assertEqual(resource["label"], "Sem recurso informado")
        leaf = resource["children"][0]
        self.assertEqual(leaf["label"], "Sem OP")
        self.assertNotIn("setor", leaf["detail"])
        self.assertNotIn("apontamento", leaf["detail"])
        self.assertTrue(tree["reconciliation"]["ok"])

    def test_gravidade_desconhecida_nao_some(self):
        issues = [_issue("critico"), _issue("gravissimo", "tipo_novo")]
        total = _stub_tree(issues, "qld.auditoria.total")
        self.assertEqual(total["value"], 2)
        self.assertTrue(total["reconciliation"]["ok"])
        self.assertIn("Gravidade não reconhecida: gravissimo", [n["label"] for n in total["children"]])
        self.assertTrue(any("gravidade não reconhecida" in n for n in total["notes"]))

        critico = _stub_tree(issues, "qld.auditoria.critico")
        self.assertEqual(critico["value"], 1)
        self.assertTrue(critico["reconciliation"]["ok"])
        excluded = {item["label"]: item["value"] for item in critico["excluded"]}
        self.assertEqual(excluded["Gravidade não reconhecida"], 1.0)

    def test_tipo_desconhecido_ganha_rotulo_legivel(self):
        tree = _stub_tree([_issue("erro", "regra_nova_qualquer")], "qld.auditoria.erro")
        self.assertEqual(tree["children"][0]["label"], "Regra nova qualquer")

    def test_divergencia_aparece_na_reconciliacao(self):
        class _Torta(_StubAudit):
            def run_period(self, filters):
                payload = super().run_period(filters)
                payload["by_severity"]["critico"] = 5  # cartão diferente da lista
                return payload

        service = QualityExplanationService(None, _Torta([_issue()]), now_func=lambda: AGORA)
        tree = service.explain("qld.auditoria.critico", _filters()).to_dict()
        self.assertEqual(tree["value"], 5)
        self.assertFalse(tree["reconciliation"]["ok"])
        self.assertEqual(tree["reconciliation"]["diff"], -4.0)


class UnknownAndContextTests(unittest.TestCase):
    def test_id_desconhecido(self):
        service = QualityExplanationService(None, _StubAudit([]))
        for metric in ("qld.inexistente", "qld.auditoria.info", "qld.auditoria"):
            with self.subTest(metric), self.assertRaises(UnknownMetricError):
                service.explain(metric, _filters())

    def test_contexto_da_ia_renderiza_count_e_grupos(self):
        tree = _stub_tree([_issue(), _issue("erro", "op_sem_operador")], "qld.auditoria.total")
        context = build_explanation_context(tree, max_tokens=4000)
        self.assertIn("Valor: 2", context)
        self.assertIn("Composição (grupo > recurso > registro):", context)
        self.assertIn('"Críticos": 1', context)
        self.assertIn('"Fim antes do início": 1', context)


class QualityEndpointTests(unittest.TestCase):
    def setUp(self):
        db = _ApiRepo()
        self.app = create_app(settings=_settings(), database_factory=lambda: db)
        self.app.dependency_overrides[get_database] = lambda: db
        self.app.dependency_overrides[require_csrf] = lambda: None
        self.app.dependency_overrides[get_current_user] = lambda: _user("gestor", management=True)
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)
        self.facade = _facade(db)

    def _get(self, metric):
        return self.client.get(URL, params={"metric": metric, **PERIOD})

    def test_qualidade_pela_api_igual_a_tela(self):
        totals = self.client.get("/api/v1/analytics/quality", params=PERIOD).json()["totals"]
        for metric, kind in (("qld.boa", "boa"), ("qld.refugo", "refugo"), ("qld.retrabalho", "retrabalho")):
            with self.subTest(metric):
                response = self._get(metric)
                self.assertEqual(response.status_code, 200, response.text)
                body = response.json()
                self.assertEqual(body["kind"], "value")
                self.assertEqual(body["value"], totals[kind])
                self.assertTrue(body["reconciliation"]["ok"])

    def test_auditoria_pela_api_igual_aos_cartoes_de_alertas(self):
        db = _BaseRepo(facts=_audit_facts())  # gera críticos e erros de verdade
        self.app.dependency_overrides[get_database] = lambda: db
        alerts = self.client.get("/api/v1/management/alerts", params=PERIOD).json()
        self.assertGreater(alerts["by_severity"]["critico"], 0)
        self.assertGreater(alerts["by_severity"]["erro"], 0)
        for metric, expected in (
            ("qld.auditoria.total", alerts["count"]),
            ("qld.auditoria.critico", alerts["by_severity"].get("critico", 0)),
            ("qld.auditoria.erro", alerts["by_severity"].get("erro", 0)),
            ("qld.auditoria.aviso", alerts["by_severity"].get("aviso", 0)),
        ):
            with self.subTest(metric):
                response = self._get(metric)
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(response.json()["value"], expected)
                self.assertEqual(response.json()["unit"], "count")

    def test_id_qld_desconhecido_422(self):
        response = self._get("qld.auditoria.qualquer")
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["code"], "unknown_metric")

    def test_operador_oculto_para_quem_nao_e_gestao(self):
        gestor = explain_for_user(self.facade, "qld.refugo", _filters(), _user("gestor", management=True))
        outro = explain_for_user(
            self.facade, "qld.refugo", _filters(), _user("operador_dobra", management=False)
        )
        self.assertEqual(next(_leaves(gestor["children"]))["detail"]["operador"], "Maria")
        self.assertIsNone(next(_leaves(outro["children"]))["detail"]["operador"])


if __name__ == "__main__":
    unittest.main()
