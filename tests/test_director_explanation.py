"""Explicação clicável da Diretoria (Lote 4, ``dir.*``): conta aberta dos números em R$ e horas.

Sem banco: usa o repositório em memória de ``tests/test_director_summary.py``.
Cobre a conferência (itens somam o número clicado), custo faltando, filtros,
valor da hora por máquina e por pessoa, erros estruturados e o acesso (só
admin/diretoria; ``/management/explicacao`` nunca devolve ``dir.*``).
"""

from __future__ import annotations

import unittest

from app.core.permissions import USER_LEVELS
from backend.api.dependencies.auth import get_current_user
from mes.services.director_explanation import METRICS, DirectorExplanationService
from mes.services.director_summary import DirectorSummaryError
from tests.test_director_api import BASE, _ApiCase
from tests.test_director_summary import NOW, _Repo, _with_rates


def _explain(repo, metric, period="semana", **kwargs):
    return DirectorExplanationService(repo).explain(metric, period, now=NOW, **kwargs).to_dict()


class DirectorExplanationServiceTests(unittest.TestCase):
    def setUp(self):
        self.repo = _with_rates(_Repo())

    def test_todos_os_numeros_conferem_com_e_sem_valor_da_hora(self):
        for repo in (self.repo, _Repo()):
            for metric in METRICS:
                kwargs = {"setor": "Corte"} if metric == "dir.custo_setor" else {}
                if metric == "dir.valor_hora":
                    kwargs = {"recurso": "LASER1"}
                tree = _explain(repo, metric, **kwargs)
                self.assertEqual(tree["metric"], metric)
                self.assertTrue(tree["reconciliation"]["ok"], (metric, tree["reconciliation"]))
                self.assertTrue(tree["reason"] and tree["rule"], metric)

    def test_valores_da_semana_batem_com_o_painel(self):
        self.assertEqual(_explain(self.repo, "dir.produzido")["value"], 148)
        self.assertEqual(_explain(self.repo, "dir.horas_paradas")["value"], 14.5)
        self.assertEqual(_explain(self.repo, "dir.custo_parada")["value"], 2460.0)
        self.assertEqual(_explain(self.repo, "dir.custo_trabalho")["value"], 8110.0)
        self.assertEqual(_explain(self.repo, "dir.trabalhou")["value"], 40)
        self.assertEqual(_explain(self.repo, "dir.custo_setor", setor="Corte")["value"], 2250.0)

    def test_custo_sem_valor_da_hora_zera_e_avisa_quem_falta(self):
        tree = _explain(_Repo(), "dir.custo_parada")
        self.assertEqual(tree["value"], 0)
        self.assertTrue(any("valor da hora" in note.lower() for note in tree["notes"]), tree["notes"])

    def test_valor_hora_por_maquina_e_por_pessoa(self):
        machine = _explain(self.repo, "dir.valor_hora", recurso="LASER1")
        self.assertEqual(machine["value"], 150.0)
        self.assertEqual(machine["unit"], "brl")
        self.assertTrue(any("histórico" in note for note in machine["notes"]), machine["notes"])
        person = _explain(self.repo, "dir.valor_hora", pessoa="1")
        self.assertEqual(person["value"], 100.0)
        nobody = _explain(_Repo(), "dir.valor_hora", recurso="LASER1")
        self.assertIsNone(nobody["value"])
        self.assertTrue(any("sem valor cadastrado" in child["label"] for child in nobody["children"]), nobody["children"])

    def test_motivo_abre_so_as_horas_daquele_motivo(self):
        tree = _explain(self.repo, "dir.parado_motivo", motivo="Falta de Material")
        self.assertEqual(tree["value"], 6.0)
        self.assertTrue(tree["reconciliation"]["ok"], tree["reconciliation"])
        self.assertIn("falta de material", tree["label"].lower())
        self.assertLess(tree["value"], _explain(self.repo, "dir.parado_motivo")["value"])

    def test_motivo_desconhecido_vale_zero_sem_erro(self):
        tree = _explain(self.repo, "dir.parado_motivo", motivo="motivo que nao existe")
        self.assertEqual(tree["value"], 0)
        self.assertTrue(tree["reconciliation"]["ok"], tree["reconciliation"])

    def test_filtro_de_recurso_restringe_a_conta(self):
        full = _explain(self.repo, "dir.custo_parada")["value"]
        laser = _explain(self.repo, "dir.custo_parada", recurso="LASER1")
        self.assertLess(laser["value"], full)
        self.assertTrue(laser["reconciliation"]["ok"])

    def test_erros_estruturados(self):
        cases = (
            (dict(metric="dir.nao_existe"), "UNKNOWN_METRIC", 422),
            (dict(metric=""), "UNKNOWN_METRIC", 422),
            (dict(metric="dir.custo_setor"), "SECTOR_REQUIRED", 422),
            (dict(metric="dir.valor_hora"), "RATE_TARGET_REQUIRED", 422),
            (dict(metric="dir.valor_hora", pessoa="999"), "UNKNOWN_PERSON", 404),
        )
        for kwargs, code, status in cases:
            with self.assertRaises(DirectorSummaryError) as raised:
                DirectorExplanationService(self.repo).explain(period="semana", now=NOW, **kwargs)
            self.assertEqual(raised.exception.code, code, kwargs)
            self.assertEqual(raised.exception.status_code, status, kwargs)

    def test_periodo_invalido_e_erro_de_regra_nao_500(self):
        with self.assertRaises(DirectorSummaryError):
            DirectorExplanationService(self.repo).explain("dir.produzido", "ontem-e-hoje", now=NOW)


class DirectorExplanationApiTests(_ApiCase):
    def setUp(self):
        self._build(_with_rates(_Repo()))

    def test_diretoria_e_admin_abrem_a_conta(self):
        for role in ("diretoria", "admin"):
            self._as(role)
            response = self.client.get(f"{BASE}/explicacao", params={"metric": "dir.custo_parada", "periodo": "semana"})
            self.assertEqual(response.status_code, 200, (role, response.text))
            body = response.json()
            self.assertEqual(body["kind"], "value")
            self.assertEqual(body["unit"], "brl")
            self.assertEqual(body["value"], 2460.0)
            self.assertTrue(body["reconciliation"]["ok"])

    def test_filtros_chegam_ao_servico(self):
        self._as("diretoria")
        response = self.client.get(
            f"{BASE}/explicacao", params={"metric": "dir.valor_hora", "recurso": "LASER1", "periodo": "semana"}
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["value"], 150.0)

    def test_erro_de_regra_vira_json_estruturado(self):
        self._as("diretoria")
        unknown = self.client.get(f"{BASE}/explicacao", params={"metric": "dir.xyz"})
        self.assertEqual((unknown.status_code, unknown.json()["code"]), (422, "UNKNOWN_METRIC"))
        no_sector = self.client.get(f"{BASE}/explicacao", params={"metric": "dir.custo_setor"})
        self.assertEqual((no_sector.status_code, no_sector.json()["code"]), (422, "SECTOR_REQUIRED"))
        no_person = self.client.get(f"{BASE}/explicacao", params={"metric": "dir.valor_hora", "pessoa": "999"})
        self.assertEqual(no_person.status_code, 404)
        missing = self.client.get(f"{BASE}/explicacao")
        self.assertEqual(missing.status_code, 422)

    def test_todo_outro_nivel_recebe_403_sem_r(self):
        others = [level for level in USER_LEVELS if level not in ("admin", "diretoria")]
        self.assertGreater(len(others), 10)
        for level in others:
            self._as(level)
            response = self.client.get(f"{BASE}/explicacao", params={"metric": "dir.custo_parada"})
            self.assertEqual(response.status_code, 403, (level, response.text))
            self.assertEqual(response.json()["code"], "director_access_denied")
            self.assertNotIn("value", response.json())

    def test_sem_sessao_401(self):
        self.app.dependency_overrides.pop(get_current_user, None)
        self.assertEqual(self.client.get(f"{BASE}/explicacao", params={"metric": "dir.produzido"}).status_code, 401)

    def test_rota_de_gestao_nao_serve_dir(self):
        self._as("admin")
        response = self.client.get("/api/v1/management/explicacao", params={"metric": "dir.custo_parada"})
        self.assertEqual(response.status_code, 422, response.text)
        self.assertNotIn("2460", response.text)


if __name__ == "__main__":
    unittest.main()
